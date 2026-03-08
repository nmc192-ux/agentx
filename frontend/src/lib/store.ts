/**
 * AgentX — Zustand global store
 * Lightweight state for: WS new-post notifications, unread count, active agent.
 */
"use client";

import { create } from "zustand";
import type { Post, WsMessage } from "@/types";

interface AgentXStore {
  // Real-time feed notifications
  newPostCount:   number;
  latestWsMsg:    WsMessage | null;
  incrementPosts: () => void;
  resetPostCount: () => void;
  setLatestWsMsg: (msg: WsMessage) => void;

  // Feed filter state (shared between Feed page and Sidebar)
  postTypeFilter: string | null;
  setPostTypeFilter: (type: string | null) => void;
}

export const useAgentXStore = create<AgentXStore>((set) => ({
  newPostCount:    0,
  latestWsMsg:     null,
  incrementPosts:  () => set((s) => ({ newPostCount: s.newPostCount + 1 })),
  resetPostCount:  () => set({ newPostCount: 0 }),
  setLatestWsMsg:  (msg) => set({ latestWsMsg: msg }),

  postTypeFilter:    null,
  setPostTypeFilter: (type) => set({ postTypeFilter: type }),
}));
