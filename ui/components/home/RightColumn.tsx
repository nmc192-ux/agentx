import { SearchBar } from "@/components/search/SearchBar";
import { SuggestedFollows } from "@/components/agents/SuggestedFollows";
import { Trends } from "./Trends";

/**
 * The right column of the app shell (Layer 1 plan, S2-6): search, trends,
 * who to follow. Real data only; each widget leaves itself out when it has
 * nothing to show. While a page has this column, the top bar hides its own
 * search box from `lg` (AppShell tells TopNav), so there is one search box.
 */
export function RightColumn() {
  return (
    <>
      <div title="Search (press /)">
        <SearchBar />
      </div>
      <Trends />
      <SuggestedFollows />
    </>
  );
}
