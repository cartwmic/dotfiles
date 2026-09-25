<?php
// Run only via router-phone.py over root SSH on OPNsense. Input contains public
// identifiers only. Never serialize config.xml or server/private client keys.
require_once 'config.inc';

function fail_phone(string $message): never {
    fwrite(STDERR, "phone peer: $message\n");
    exit(2);
}
function one_named(array $entries, string $name, string $field): ?int {
    $found = null;
    foreach ($entries as $index => $entry) {
        if (($entry[$field] ?? '') !== $name) continue;
        if ($found !== null) fail_phone("multiple entries named $name");
        $found = $index;
    }
    return $found;
}
function public_key(string $value): bool {
    $raw = base64_decode($value, true);
    return $raw !== false && strlen($raw) === 32;
}
function safe_state(array $clients, array $maps, array $server): array {
    return [
        'server' => [($server['@attributes']['uuid'] ?? ''), ($server['pubkey'] ?? ''), ($server['peers'] ?? '')],
        'clients' => array_map(static fn($c) => [
            ($c['@attributes']['uuid'] ?? ''), ($c['name'] ?? ''), ($c['pubkey'] ?? ''),
            ($c['tunneladdress'] ?? ''), ($c['enabled'] ?? '')
        ], $clients),
        'maps' => array_map(static fn($m) => [($m['hostname'] ?? ''), ($m['ipaddr'] ?? ''), ($m['mac'] ?? '')], $maps),
    ];
}
function describe_client(?array $c): ?array {
    if ($c === null) return null;
    return [
        'uuid' => $c['@attributes']['uuid'] ?? '', 'name' => $c['name'] ?? '',
        'public_key' => $c['pubkey'] ?? '', 'address' => $c['tunneladdress'] ?? '',
    ];
}
function describe_map(?array $m): ?array {
    if ($m === null) return null;
    return ['mac' => $m['mac'] ?? '', 'lan' => $m['ipaddr'] ?? '', 'hostname' => $m['hostname'] ?? ''];
}

$encoded = getenv('PHONE_SPEC_B64');
$spec = json_decode(base64_decode($encoded ?: '', true) ?: '', true);
if (!is_array($spec)) fail_phone('invalid request');
$action = $spec['action'] ?? '';
$mode = $spec['mode'] ?? '';
if (!in_array($action, ['inspect', 'plan', 'apply'], true)
    || !in_array($mode, ['inspect', 'stage', 'restore', 'retire'], true)) fail_phone('unknown action/mode');

$wg =& $config['OPNsense']['wireguard'];
$clients =& $wg['client']['clients']['client'];
$servers =& $wg['server']['servers'];
$maps =& $config['dhcpd']['lan']['staticmap'];
if (!is_array($clients) || !is_array($servers) || count($servers) !== 1
    || !is_array($servers[0]['server'] ?? null) || !is_array($maps)) fail_phone('unsupported router schema');
$server =& $servers[0]['server'];
if (($server['instance'] ?? '') != '1' || ($server['name'] ?? '') !== 'cartwmic-homelab'
    || !public_key($server['pubkey'] ?? '')) fail_phone('unexpected WireGuard instance');
$oldIndex = one_named($clients, 'cartwmic-ssh-phone', 'name');
$nextIndex = one_named($clients, 'cartwmic-ssh-phone-candidate', 'name');
$oldMapIndex = one_named($maps, 'ssh-phone', 'hostname');
$nextMapIndex = one_named($maps, 'ssh-phone-candidate', 'hostname');
if ($oldIndex === null || $oldMapIndex === null) fail_phone('existing ssh-phone peer/reservation missing');
$old = $clients[$oldIndex];
$oldMap = $maps[$oldMapIndex];
if (!preg_match('/^10\\.21\\.1\\.([2-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-4])\\/32$/', $old['tunneladdress'] ?? '')
    || !preg_match('/^10\\.19\\.1\\.([2-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-4])$/', $oldMap['ipaddr'] ?? '')
    || !public_key($old['pubkey'] ?? '')) fail_phone('existing ssh-phone identity has unsupported address/key');
$peers = array_filter(explode(',', $server['peers'] ?? ''));
if (!in_array($old['@attributes']['uuid'] ?? '', $peers, true)) fail_phone('old peer not attached to wg1');
$state = safe_state($clients, $maps, $server);
$summary = [
    'fingerprint' => hash('sha256', json_encode($state)),
    'server_public_key' => $server['pubkey'],
    'old_peer' => describe_client($old),
    'old_reservation' => describe_map($oldMap),
    'candidate_peer' => describe_client($nextIndex === null ? null : $clients[$nextIndex]),
    'candidate_reservation' => describe_map($nextMapIndex === null ? null : $maps[$nextMapIndex]),
];
if ($action === 'inspect') {
    echo json_encode($summary, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES), "\n";
    exit(0);
}

$mac = strtolower($spec['mac'] ?? '');
$lan = $spec['lan'] ?? '';
$address = $spec['address'] ?? '';
$pub = $spec['public_key'] ?? '';
if (!preg_match('/^[0-9a-f]{2}(:[0-9a-f]{2}){5}$/', $mac)
    || !filter_var($lan, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4)
    || !str_starts_with($lan, '10.19.1.') || !str_starts_with($address, '10.21.1.')
    || !preg_match('/^10\.21\.1\.(\d{1,3})\/32$/', $address, $matches)
    || (int)$matches[1] < 2 || (int)$matches[1] > 254
    || (int)substr($lan, strrpos($lan, '.') + 1) < 2
    || (int)substr($lan, strrpos($lan, '.') + 1) > 254
    || !public_key($pub)) fail_phone('invalid requested MAC/IP/public key');
if ($mode === 'restore') {
    if ($address !== ($old['tunneladdress'] ?? '') || $lan !== ($oldMap['ipaddr'] ?? '')
        || $pub !== ($old['pubkey'] ?? '')) fail_phone('restore must match the existing peer and addresses');
} elseif ($mode === 'stage' || $mode === 'retire') {
    if ($address === ($old['tunneladdress'] ?? '') || $lan === ($oldMap['ipaddr'] ?? '')
        || $pub === ($old['pubkey'] ?? '')) fail_phone('replacement must have distinct peer, IP and public key');
}
foreach ($clients as $i => $client) {
    if ($i === $nextIndex && $mode !== 'restore') continue;
    if (($client['tunneladdress'] ?? '') === $address && $mode !== 'restore') fail_phone('WireGuard address already reserved');
    if (($client['pubkey'] ?? '') === $pub && $i !== $oldIndex) fail_phone('public key already belongs to another peer');
}
foreach ($maps as $i => $map) {
    if ($i === $nextMapIndex && $mode !== 'restore') continue;
    if ($i === $oldMapIndex && $mode === 'restore') continue;
    if (($map['ipaddr'] ?? '') === $lan || strtolower($map['mac'] ?? '') === $mac) fail_phone('LAN IP/MAC is used by another reservation');
}
if ($mode !== 'restore' && $nextIndex !== null) {
    $next = $clients[$nextIndex];
    if (($next['tunneladdress'] ?? '') !== $address || ($next['pubkey'] ?? '') !== $pub
        || ($next['enabled'] ?? '') != '1') fail_phone('candidate peer conflicts with requested identity');
}
if ($mode !== 'restore' && $nextMapIndex !== null) {
    $nextMap = $maps[$nextMapIndex];
    if (($nextMap['ipaddr'] ?? '') !== $lan || strtolower($nextMap['mac'] ?? '') !== $mac)
        fail_phone('candidate reservation conflicts with requested identity');
}
if ($mode === 'retire' && ($nextIndex === null || $nextMapIndex === null
    || !in_array($clients[$nextIndex]['@attributes']['uuid'] ?? '', $peers, true)))
    fail_phone('candidate must be staged and attached to wg1 before retirement');
$summary['mode'] = $mode;
$summary['proposed'] = ['mac' => $mac, 'lan' => $lan, 'address' => $address, 'public_key' => $pub];
$summary['changes'] = match ($mode) {
    'stage' => ['upsert candidate peer/reservation', 'reload WireGuard template', 'configure WireGuard', 'restart DHCP'],
    'restore' => ['update existing reservation MAC only', 'restart DHCP if changed'],
    'retire' => ['remove old peer/reservation', 'rename candidate to ssh-phone', 'reload WireGuard template', 'configure WireGuard', 'restart DHCP'],
    default => fail_phone('bad mode'),
};
if ($action === 'plan') {
    echo json_encode($summary, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES), "\n";
    exit(0);
}
if (($spec['expected_fingerprint'] ?? '') !== $summary['fingerprint'])
    fail_phone('router state changed since plan; inspect and plan again');
$changed = false;
$candidateAttached = $nextIndex !== null
    && in_array($clients[$nextIndex]['@attributes']['uuid'] ?? '', $peers, true);
if ($mode === 'stage' && ($nextIndex === null || $nextMapIndex === null || !$candidateAttached))
    $changed = true;
if ($mode === 'restore' && strtolower($oldMap['mac'] ?? '') !== $mac) $changed = true;
if ($mode === 'retire') $changed = true;
if ($changed) {
    // The backup remains only on OPNsense, which already owns config.xml.
    $backup = '/conf/backup/config-phone-' . gmdate('Ymd-His') . '-' . bin2hex(random_bytes(4)) . '.xml';
    $oldUmask = umask(0077);
    $backedUp = copy('/conf/config.xml', $backup);
    umask($oldUmask);
    if (!$backedUp || !chmod($backup, 0600)) {
        @unlink($backup);
        fail_phone('router config backup failed');
    }
    if ($mode === 'stage') {
        if ($nextIndex === null) {
            $uuid = sprintf('%s-%s-%s-%s-%s', bin2hex(random_bytes(4)), bin2hex(random_bytes(2)),
                bin2hex(random_bytes(2)), bin2hex(random_bytes(2)), bin2hex(random_bytes(6)));
            $clients[] = [
                '@attributes' => ['uuid' => $uuid], 'enabled' => '1',
                'name' => 'cartwmic-ssh-phone-candidate', 'pubkey' => $pub,
                'tunneladdress' => $address, 'serveraddress' => '', 'serverport' => '',
                'keepalive' => '25',
            ];
            $peers[] = $uuid;
            $server['peers'] = implode(',', $peers);
        } elseif (!$candidateAttached) {
            $peers[] = $clients[$nextIndex]['@attributes']['uuid'];
            $server['peers'] = implode(',', $peers);
        }
        if ($nextMapIndex === null) $maps[] = ['mac' => $mac, 'ipaddr' => $lan,
            'hostname' => 'ssh-phone-candidate', 'descr' => 'replacement phone candidate'];
    } elseif ($mode === 'restore') {
        $maps[$oldMapIndex]['mac'] = $mac;
    } else {
        $oldUuid = $old['@attributes']['uuid'];
        $peers = array_values(array_filter($peers, static fn($id) => $id !== $oldUuid));
        $server['peers'] = implode(',', $peers);
        unset($clients[$oldIndex], $maps[$oldMapIndex]);
        $clients = array_values($clients);
        $maps = array_values($maps);
        $newClientIndex = one_named($clients, 'cartwmic-ssh-phone-candidate', 'name');
        $newMapIndex = one_named($maps, 'ssh-phone-candidate', 'hostname');
        $clients[$newClientIndex]['name'] = 'cartwmic-ssh-phone';
        $maps[$newMapIndex]['hostname'] = 'ssh-phone';
        $maps[$newMapIndex]['descr'] = 'replacement phone';
    }
    write_config('Phone ssh-phone ' . $mode . ' (reviewed, backed up)');
    $summary['backup'] = $backup;
}
$summary['changed'] = $changed;
echo json_encode($summary, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES), "\n";
