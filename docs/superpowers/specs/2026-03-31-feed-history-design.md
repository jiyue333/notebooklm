# Feed History Load Design

## Goal

When a user opens a single RSS feed in the feed workspace and reaches the end of the currently visible articles, they should be able to click `查看更多历史文章` and load older articles that are not already present in the in-app feed list.

The button must trigger a real history-fetch action instead of only changing filters or reusing the current Miniflux page.

## Scope

- Add a backend action to discover and persist older feed articles.
- Return persisted history entries together with normal Miniflux feed entries in the single-feed article list.
- Support existing feed actions for persisted history entries where practical:
  - expand full content
  - generate AI summary
  - import to notebook
  - mark read
- Add a feed workspace button that explicitly loads older articles for the currently selected feed.

## Non-Goals

- Do not build a generalized crawler platform.
- Do not redesign the feed workspace layout.
- Do not optimize for large-scale pagination beyond the current modal use case.

## Backend Design

### Persistence

Add a new table for persisted historical RSS entries owned by a user and linked to a local RSS feed record.

Each row stores:

- feed relationship
- dedupe key
- source URL
- title
- author
- published timestamp
- content HTML
- read/star state

Historical entries are exposed as synthetic negative `entryId` values in the API so the existing frontend can continue using numeric entry IDs without colliding with Miniflux entry IDs.

### Load-History Action

Add `POST /feeds/{feed_id}/history/load`.

Flow:

1. Resolve the local feed and collect known article URLs from:
   - current Miniflux feed entries
   - previously persisted historical entries
2. Determine the oldest known article for this feed.
3. Discover older candidate article links by scanning:
   - the monthly archive page derived from the oldest known article URL when possible
   - the previous monthly archive page from the archive page `rel="prev"` link when available
   - the site homepage / archive page as fallback
4. Fetch candidate article pages, extract article metadata and content, and persist only new entries.
5. Return how many new historical entries were added.

This is intentionally best-effort. Some sites will expose archives cleanly; some will not. When no additional older article can be discovered, the API returns `loadedCount = 0`.

### List Entries

For single-feed entry lists, merge:

- Miniflux feed entries
- persisted historical entries

Sort the combined set by `publishedAt` descending, then apply `offset` and `limit`.

### Entry Detail and Actions

Existing detail/status/summary/import flows must accept synthetic negative entry IDs and route them to persisted historical entries instead of Miniflux when needed.

## Frontend Design

In the feed workspace modal:

- When a single feed is selected and the user is not in search mode, show `查看更多历史文章` at the bottom of the article list.
- Clicking it calls the new backend history-load action.
- On success:
  - refresh the current feed entry list
  - append any newly discovered historical entries into the list naturally through the merged list response
- If the action returns zero new entries:
  - show a terminal empty-state message like `没有更多历史文章`
  - stop retrying automatically for the current selection unless the user changes feeds or refreshes

## Error Handling

- If the target feed is missing, return 404.
- If the feed site cannot be fetched, return a clear 4xx/5xx app error message.
- If history discovery fails for a specific site structure, return a user-facing failure instead of silently pretending all history is exhausted.

## Verification

- Backend: exercise the new history-load service and ensure merged single-feed list responses include persisted history rows.
- Frontend: verify the button appears for a selected feed, triggers loading, and shows a terminal no-more-history state when appropriate.
