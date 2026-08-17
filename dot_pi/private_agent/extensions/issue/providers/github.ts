/**
 * GitHub provider — backed by the `gh` CLI.
 * No MCP config needed; auth is handled by `gh auth login/status`.
 */
import { execFile, execSync } from "node:child_process";
import { promisify } from "node:util";
import type { CreateIssueInput, Issue, IssueProvider, SearchResult } from "./types.ts";

const execFileAsync = promisify(execFile);

/** Parse "123" or "owner/repo#123" into { repo?: string; number: number }. */
export function parseGitHubIssueRef(ref: string): { repo?: string; number: number } | null {
	const trimmed = ref.trim();
	const fullMatch = trimmed.match(/^([^/]+\/[^#]+)#(\d+)$/);
	if (fullMatch) {
		return { repo: fullMatch[1], number: parseInt(fullMatch[2], 10) };
	}
	const numMatch = trimmed.match(/^(\d+)$/);
	if (numMatch) {
		return { number: parseInt(numMatch[1], 10) };
	}
	return null;
}

async function gh(args: string[]): Promise<string> {
	try {
		const { stdout, stderr } = await execFileAsync("gh", args, {
			encoding: "utf8",
			timeout: 30_000,
		});
		if (stderr && !stdout) {
			throw new Error(stderr.trim());
		}
		return stdout;
	} catch (err: unknown) {
		const msg =
			err instanceof Error
				? "stderr" in err
					? String((err as { stderr?: string }).stderr ?? err.message)
					: err.message
				: String(err);
		throw new Error(`gh ${args[0]} failed: ${msg.trim()}`);
	}
}

function ghAvailable(): boolean {
	try {
		execSync("gh --version", { stdio: "ignore", timeout: 5_000 });
		return true;
	} catch {
		return false;
	}
}

/** Get current repo as "owner/name" or null if not in a repo. */
async function currentRepo(): Promise<string | null> {
	try {
		const out = await gh(["repo", "view", "--json", "owner,name"]);
		const data = JSON.parse(out) as { owner?: { login?: string }; name?: string };
		const owner = data.owner?.login;
		const name = data.name;
		if (owner && name) return `${owner}/${name}`;
		return null;
	} catch {
		return null;
	}
}

interface GhIssueJson {
	number: number;
	title: string;
	body?: string;
	state: string;
	url: string;
	repository?: { nameWithOwner?: string };
}

function toIssue(data: GhIssueJson, repo?: string): Issue {
	const repoName = repo ?? data.repository?.nameWithOwner ?? "unknown";
	const fullKey = `${repoName}#${data.number}`;
	return {
		key: fullKey,
		displayKey: fullKey,
		title: data.title,
		body: data.body,
		status: data.state,
		url: data.url,
		provider: "github",
	};
}

export class GitHubProvider implements IssueProvider {
	readonly name = "github";
	readonly isAvailable = ghAvailable();

	async getIssue(key: string): Promise<Issue> {
		const parsed = parseGitHubIssueRef(key);
		if (!parsed) {
			throw new Error(`Invalid GitHub issue reference: "${key}". Use "123" or "owner/repo#123".`);
		}
		const repo = parsed.repo ?? (await currentRepo());
		if (!repo) {
			throw new Error(
				"Not in a git repository and no repo specified. Use \"owner/repo#123\" format.",
			);
		}
		const out = await gh(["issue", "view", String(parsed.number), "--repo", repo, "--json", "number,title,body,state,url"]);
		const data = JSON.parse(out) as GhIssueJson;
		return toIssue(data, repo);
	}

	async searchIssues(query: string): Promise<SearchResult> {
		const args = ["search", "issues", query, "--limit", "10", "--json", "number,title,state,url,repository"];
		const out = await gh(args);
		const items = JSON.parse(out) as GhIssueJson[];
		return {
			issues: items.map((item) => toIssue(item)),
			total: items.length,
		};
	}

	async createIssue(input: CreateIssueInput): Promise<Issue> {
		const repo = input.project ?? (await currentRepo());
		if (!repo) {
			throw new Error(
				"Not in a git repository and no repo specified. Set project to \"owner/repo\".",
			);
		}
		const args = [
			"issue",
			"create",
			"--repo",
			repo,
			"--title",
			input.title,
			"--body",
			input.body ?? "",
		];
		const out = await gh(args);
		const url = out.trim();
		const numMatch = url.match(/\/issues\/(\d+)$/);
		if (!numMatch) {
			throw new Error(`Could not parse issue number from create output: ${url}`);
		}
		const number = parseInt(numMatch[1], 10);
		const viewOut = await gh([
			"issue",
			"view",
			String(number),
			"--repo",
			repo,
			"--json",
			"number,title,body,state,url",
		]);
		const data = JSON.parse(viewOut) as GhIssueJson;
		return toIssue(data, repo);
	}

	async addComment(key: string, body: string): Promise<void> {
		const parsed = parseGitHubIssueRef(key);
		if (!parsed) {
			throw new Error(`Invalid GitHub issue reference: "${key}"`);
		}
		const repo = parsed.repo ?? (await currentRepo());
		if (!repo) {
			throw new Error("Not in a git repository and no repo specified.");
		}
		await gh([
			"issue",
			"comment",
			String(parsed.number),
			"--repo",
			repo,
			"--body",
			body,
		]);
	}
}
