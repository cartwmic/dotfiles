/**
 * Common issue-tracking semantics across providers.
 */

export interface Issue {
	/** Canonical key within the provider (e.g. "PROJ-123", "42"). */
	key: string;
	/** Human-readable display key (e.g. "PROJ-123", "owner/repo#42"). */
	displayKey: string;
	title: string;
	body?: string;
	status: string;
	url: string;
	provider: string;
}

export interface Transition {
	id: string;
	name: string;
}

export interface SearchResult {
	issues: Issue[];
	total: number;
}

export interface CreateIssueInput {
	title: string;
	body?: string;
	/** Jira project key, GitHub repo (owner/repo), etc. */
	project?: string;
	/** Provider-specific extras passed through. */
	[key: string]: unknown;
}

export interface IssueProvider {
	readonly name: string;
	readonly isAvailable: boolean;

	getIssue(key: string): Promise<Issue>;
	searchIssues(query: string): Promise<SearchResult>;
	createIssue(input: CreateIssueInput): Promise<Issue>;
	addComment(key: string, body: string): Promise<void>;

	/** Jira-only; optional because GitHub has no transitions. */
	listTransitions?(key: string): Promise<Transition[]>;
	transitionIssue?(key: string, transitionId: string): Promise<void>;
}
