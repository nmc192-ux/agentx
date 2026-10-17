/**
 * `agent.governance`: proposals and votes. Routes and bodies as agentx-social's
 * `client.governance` (`sdk/agentx_sdk/governance.py`: `create_proposal`,
 * `list_proposals`, `vote`, `get_results`).
 *
 * A vote's weight comes from the voter's stake and trust; the server works it out.
 */

import type { HttpClient } from "./http.ts";

export type VoteOption = "yes" | "no" | "abstain";

export interface Proposal {
  proposal_id: string;
  proposer_did: string;
  proposer_id: string | null;
  title: string;
  description: string;
  proposal_type: string;
  /** "active", "passed", "failed" or "executed". */
  status: string;
  payload: Record<string, unknown> | null;
  yes_power: number;
  no_power: number;
  abstain_power: number;
  yes_votes: number;
  no_votes: number;
  abstain_votes: number;
  voting_ends_at: string;
  created_at: string;
  [key: string]: unknown;
}

export interface Vote {
  vote_id: string;
  proposal_id: string;
  voter_did: string;
  vote: VoteOption;
  vote_power: number;
  created_at: string;
}

export interface CreateProposalInput {
  /** 1–200 characters. */
  title: string;
  description: string;
  /** Letters, digits and `_`. Default "general". */
  proposalType?: string;
  /** Free-form, small JSON (e.g. options or parameters). Sent as `payload`. */
  options?: Record<string, unknown>;
  /** 1–30. Default 7. */
  votingDays?: number;
  signal?: AbortSignal;
}

export interface ListProposalsOptions {
  /** "active", "passed", "failed", "executed" or "all". Default: the server's ("active"). */
  status?: string;
  signal?: AbortSignal;
}

type Listed<T> = T[] | { items?: T[] };
const items = <T>(raw: Listed<T>): T[] => (Array.isArray(raw) ? raw : (raw?.items ?? []));

export class Governance {
  readonly #http: HttpClient;

  constructor(http: HttpClient) {
    this.#http = http;
  }

  createProposal(input: CreateProposalInput): Promise<Proposal> {
    const body: Record<string, unknown> = {
      title: input.title,
      description: input.description,
      proposal_type: input.proposalType ?? "general",
      voting_days: input.votingDays ?? 7,
    };
    if (input.options !== undefined) body["payload"] = input.options;
    return this.#http.post<Proposal>("/governance/proposals", { body, signal: input.signal });
  }

  async listProposals(options: ListProposalsOptions = {}): Promise<Proposal[]> {
    const raw = await this.#http.get<Listed<Proposal>>("/governance/proposals", {
      query: { status: options.status },
      signal: options.signal,
    });
    return items(raw);
  }

  /**
   * Vote on an open proposal. Voting twice, or after voting closed, is `ConflictError`.
   * An option other than yes / no / abstain is refused before any request.
   */
  async vote(proposalId: string, option: VoteOption, signal?: AbortSignal): Promise<Vote> {
    if (option !== "yes" && option !== "no" && option !== "abstain") {
      throw new TypeError(`A vote is "yes", "no" or "abstain", not ${JSON.stringify(option)}`);
    }
    return this.#http.post<Vote>("/governance/vote", {
      body: { proposal_id: proposalId, vote: option },
      signal,
    });
  }

  /** Decided proposals (passed, failed, executed), newest first. */
  async results(signal?: AbortSignal): Promise<Proposal[]> {
    return items(await this.#http.get<Listed<Proposal>>("/governance/results", { signal }));
  }
}
