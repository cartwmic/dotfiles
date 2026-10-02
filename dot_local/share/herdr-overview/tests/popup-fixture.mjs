export function snapshot() {
  return { protocol: 22, version: '0.9.1', focused_workspace_id: 'w', focused_tab_id: 't1', focused_pane_id: 'p1',
    workspaces: [{ workspace_id: 'w', label: 'Synthetic workspace', active_tab_id: 't1', number: 1 }],
    tabs: [1,2,3].map(n => ({ tab_id: `t${n}`, workspace_id: 'w', label: n === 3 ? 'Multi pane group' : `Single ${n}`, number: n })),
    panes: [1,2,3,4].map(n => ({ pane_id: `p${n}`, tab_id: `t${Math.min(n,3)}`, workspace_id: 'w', terminal_id: `terminal${n}`, label: `Subject ${n}`, title: `Native title ${n}`, agent: n === 4 ? null : 'pi', agent_status: n === 3 ? 'blocked' : 'working' })), agents: [], layouts: [] };
}
