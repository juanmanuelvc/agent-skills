import {
  Button,
  Card,
  categoryPaletteDark,
  categoryPaletteLight,
  CardBody,
  CardHeader,
  Checkbox,
  DiffStats,
  DiffView,
  Divider,
  H1,
  Pill,
  Row,
  Spacer,
  Stack,
  Stat,
  Text,
  TextArea,
  TextInput,
  useCanvasAction,
  useCanvasState,
  useEffect,
  useHostTheme,
  useRef,
  useState,
} from "cursor/canvas";

type DiffLineType = "added" | "removed" | "unchanged";
type DiffLine = { type: DiffLineType; content: string; lineNumber?: number };
type ChangedFile = {
  path: string;
  status: "added" | "modified" | "deleted";
  additions: number;
  deletions: number;
  digest: string;
};
type CommitFlag = "fixup" | "wip" | "no-type" | "long-subject";
type Commit = {
  sha: string;
  shortSha: string;
  subject: string;
  body: string;
  author: string;
  date: string;
  files: number;
  additions: number;
  deletions: number;
  flags: CommitFlag[];
};
type StatusFilter = "all" | ChangedFile["status"];
type ReviewFilter = "none" | "reviewed" | "pending";
type ViewMode = "files" | "commits";

const DRILL_META = __DRILL_META__;
const GENERATED_AT = __GENERATED_AT__;
const REPO = __REPO__;
const BRANCH = __BRANCH__;
const BASE = __BASE__;
const BASE_SHA = __BASE_SHA__;
const HEAD_SHA = __HEAD_SHA__;
const UNPUSHED = __UNPUSHED__;
const DIRTY = __DIRTY__;

const FILES: ChangedFile[] = __FILES__;
const COMMITS: Commit[] = __COMMITS__;

const DIFFS: Record<string, DiffLine[]> = __DIFFS__;

const STATUS_ORDER: StatusFilter[] = ["all", "added", "modified", "deleted"];
const STATUS_LABEL: Record<StatusFilter, string> = {
  all: "All",
  added: "Added",
  modified: "Modified",
  deleted: "Deleted",
};

const FLAG_LABEL: Record<CommitFlag, string> = {
  fixup: "fixup leftover",
  wip: "WIP",
  "no-type": "no type prefix",
  "long-subject": "subject > 72",
};

function fileName(path: string): string {
  const parts = path.split("/");
  return parts[parts.length - 1] ?? path;
}

const TOTAL_ADDITIONS = FILES.reduce((sum, file) => sum + file.additions, 0);
const TOTAL_DELETIONS = FILES.reduce((sum, file) => sum + file.deletions, 0);

function DiffTotals() {
  const theme = useHostTheme();
  const palette = theme.kind === "light" ? categoryPaletteLight : categoryPaletteDark;
  return (
    <span>
      <span style={{ color: palette.green }}>+{TOTAL_ADDITIONS}</span>
      <span style={{ color: theme.text.quaternary }}> / </span>
      <span style={{ color: palette.red }}>&minus;{TOTAL_DELETIONS}</span>
    </span>
  );
}

function statusCount(status: StatusFilter): number {
  return status === "all"
    ? FILES.length
    : FILES.filter((file) => file.status === status).length;
}

function BranchChip({ name }: { name: string }) {
  const theme = useHostTheme();
  return (
    <span
      style={{
        background: theme.fill.tertiary,
        border: `1px solid ${theme.stroke.tertiary}`,
        borderRadius: 6,
        color: theme.accent.primary,
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
        fontSize: 12,
        lineHeight: "18px",
        padding: "1px 6px",
        whiteSpace: "nowrap",
      }}
    >
      {name}
    </span>
  );
}

function GroupLabel({ text }: { text: string }) {
  return (
    <Text size="small" tone="tertiary">
      {text}
    </Text>
  );
}

export default function PrFilesReview() {
  const dispatch = useCanvasAction();
  const theme = useHostTheme();
  const firstPath = FILES[0] ? FILES[0].path : "";
  const [view, setView] = useCanvasState<ViewMode>("pr-files-view", "files");
  const [query, setQuery] = useCanvasState("pr-files-query", "");
  const [selected, setSelected] = useCanvasState("pr-files-selected", firstPath);
  const [hoveredCommit, setHoveredCommit] = useCanvasState("pr-files-hovered-commit", "");
  const [reviewed, setReviewed] = useCanvasState<Record<string, boolean>>("pr-files-reviewed", {});
  const [reviewedDigest, setReviewedDigest] = useCanvasState<Record<string, string>>(
    "pr-files-reviewed-digest",
    {},
  );
  const [notes, setNotes] = useCanvasState<Record<string, string>>("pr-files-notes", {});
  const [reviewFilter, setReviewFilter] = useCanvasState<ReviewFilter>("pr-files-review-filter", "none");
  const [statusFilter, setStatusFilter] = useCanvasState<StatusFilter>("pr-files-status", "all");
  const [reloadTick, setReloadTick] = useCanvasState<number>("pr-drill-reload-tick", 0);
  const [reloading, setReloading] = useState(false);
  const [reloadHint, setReloadHint] = useState("");
  const previousGeneratedAt = useRef(GENERATED_AT);

  useEffect(() => {
    if (previousGeneratedAt.current !== GENERATED_AT) {
      previousGeneratedAt.current = GENERATED_AT;
      setReloading(false);
      setReloadHint("");
    }
    if (selected && !FILES.some((file) => file.path === selected)) {
      setSelected(firstPath);
    }
  }, [GENERATED_AT, firstPath, selected, setSelected]);

  useEffect(() => {
    if (!reloading) return;
    const timeout = window.setTimeout(() => {
      setReloading(false);
      setReloadHint("Watcher not running — re-run generate.py");
    }, 5000);
    return () => window.clearTimeout(timeout);
  }, [reloading]);

  // A file that changed since it was marked counts as pending again. Derived rather
  // than written back, so reconciliation can never re-enter the render loop. A file
  // reviewed before digests were recorded has no baseline and stays reviewed.
  const isReviewed = (file: ChangedFile): boolean => {
    if (!reviewed[file.path]) return false;
    const seen = reviewedDigest[file.path];
    return seen === undefined || seen === file.digest;
  };

  // Give those baseline-less files a digest once per generation, so their next
  // change is caught. Ref-guarded: at most one state write per reload.
  const adoptedAt = useRef("");
  useEffect(() => {
    if (adoptedAt.current === GENERATED_AT) return;
    adoptedAt.current = GENERATED_AT;
    const missing = FILES.filter(
      (file) => reviewed[file.path] && reviewedDigest[file.path] === undefined,
    );
    if (missing.length === 0) return;
    const nextDigest = { ...reviewedDigest };
    missing.forEach((file) => {
      nextDigest[file.path] = file.digest;
    });
    setReviewedDigest(nextDigest);
  }, [GENERATED_AT]);

  const markReviewed = (path: string, digest: string, checked: boolean) => {
    setReviewed({ ...reviewed, [path]: checked });
    const nextDigest = { ...reviewedDigest };
    if (checked) {
      nextDigest[path] = digest;
    } else {
      delete nextDigest[path];
    }
    setReviewedDigest(nextDigest);
  };

  const q = query.trim().toLowerCase();
  const visible = FILES.filter((file) => {
    if (statusFilter !== "all" && file.status !== statusFilter) return false;
    if (reviewFilter === "reviewed" && !isReviewed(file)) return false;
    if (reviewFilter === "pending" && isReviewed(file)) return false;
    if (q && !file.path.toLowerCase().includes(q)) return false;
    return true;
  });

  const current = FILES.find((file) => file.path === selected) ?? FILES[0];
  const lines = current ? DIFFS[current.path] ?? [] : [];
  const reviewedCount = FILES.filter(isReviewed).length;
  const remaining = FILES.length - reviewedCount;
  const statusOptions = STATUS_ORDER.filter(
    (status) => status === "all" || statusCount(status) > 0,
  );
  const flagged = COMMITS.filter((commit) => commit.flags.length > 0).length;

  return (
    <Stack gap={16}>
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 16,
          width: "100%",
        }}
      >
        <Stack gap={8}>
          <H1>PR drill</H1>
          <Text size="small" tone="secondary">
            {REPO}
          </Text>
          <Row gap={6} align="center" wrap>
            <BranchChip name={BRANCH} />
            <Text size="small" tone="tertiary">
              into
            </Text>
            <BranchChip name={BASE} />
            <Text size="small" tone="tertiary">
              {BASE_SHA}...{HEAD_SHA}
              {UNPUSHED ? " · not pushed" : ""}
            </Text>
          </Row>
          <Row gap={6} align="center" wrap>
            <Pill active={view === "files"} onClick={() => setView("files")}>
              Files
            </Pill>
            <Pill active={view === "commits"} onClick={() => setView("commits")}>
              Commits
            </Pill>
          </Row>
          <Text tone="secondary" size="small">
            {view === "files"
              ? `Files changed · local review, nothing is posted${DIRTY ? " · working tree included" : ""}`
              : "Commit sequence · newest first · hover for details"}
          </Text>
        </Stack>

        <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
          {reloadHint ? (
            <Text size="small" tone="tertiary">
              {reloadHint}
            </Text>
          ) : null}
          <Button
            variant="primary"
            disabled={reloading}
            title={`Reload ${DRILL_META.format} data from git`}
            onClick={() => {
              setReloadHint("");
              setReloading(true);
              setReloadTick(reloadTick + 1);
            }}
          >
            {reloading ? "Reloading…" : "Reload"}
          </Button>
        </div>
      </div>

      <Row gap={20} wrap>
        <Stat value={String(FILES.length)} label="Files" />
        <Stat value={String(COMMITS.length)} label="Commits" />
        <Stat value={<DiffTotals />} label={`Lines vs ${BASE}`} />
        {view === "files" ? (
          <>
            <Stat value={String(reviewedCount)} label="Reviewed" />
            <Stat value={String(remaining)} label="Pending" />
          </>
        ) : (
          <Stat value={String(flagged)} label="Flagged messages" />
        )}
      </Row>

      {view === "files" ? (
        <>
      <TextInput
        value={query}
        onChange={setQuery}
        placeholder="Filter by path…"
        style={{ maxWidth: 320 }}
      />

      <Row gap={16} align="center" justify="space-between">
        <GroupLabel text="Change type" />
        <GroupLabel text="Review state" />
      </Row>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 16,
          overflowX: "auto",
        }}
      >
        <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
          {statusOptions.map((status) => (
            <div key={status}>
              <Pill
                active={statusFilter === status}
                title={`Show only ${STATUS_LABEL[status].toLowerCase()} files`}
                onClick={() => setStatusFilter(status)}
              >
                {STATUS_LABEL[status]} {statusCount(status)}
              </Pill>
            </div>
          ))}
        </div>

        <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
          <Pill
            active={reviewFilter === "reviewed"}
            title="Toggle off to show reviewed and pending together"
            onClick={() =>
              setReviewFilter(reviewFilter === "reviewed" ? "none" : "reviewed")
            }
          >
            Reviewed {reviewedCount}
          </Pill>
          <Pill
            active={reviewFilter === "pending"}
            title="Toggle off to show reviewed and pending together"
            onClick={() =>
              setReviewFilter(reviewFilter === "pending" ? "none" : "pending")
            }
          >
            Pending {remaining}
          </Pill>
        </div>
      </div>
        </>
      ) : null}

      <Divider />

      {view === "commits" ? (
        COMMITS.length > 0 ? (
          <Stack gap={0}>
            {COMMITS.map((commit) => {
              const expanded = hoveredCommit === commit.sha;
              return (
                <div
                  key={commit.sha}
                  tabIndex={0}
                  onMouseEnter={() => setHoveredCommit(commit.sha)}
                  onMouseLeave={() => setHoveredCommit("")}
                  onFocus={() => setHoveredCommit(commit.sha)}
                  onBlur={() => setHoveredCommit("")}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "76px 22px minmax(0, 1fr)",
                    minWidth: 0,
                    outline: "none",
                  }}
                >
                  <Text size="small" tone="tertiary">
                    {commit.shortSha}
                  </Text>
                  <div
                    aria-hidden="true"
                    style={{
                      alignSelf: "stretch",
                      borderLeft: "1px solid currentColor",
                      color: theme.text.quaternary,
                      marginLeft: 7,
                      position: "relative",
                    }}
                  >
                    <span
                      style={{
                        background: theme.accent.primary,
                        border: `2px solid ${theme.accent.primary}`,
                        borderRadius: "50%",
                        display: "block",
                        height: 9,
                        left: -5,
                        position: "absolute",
                        top: 5,
                        width: 9,
                      }}
                    />
                  </div>
                  <div style={{ minWidth: 0, paddingBottom: 14 }}>
                    <Row gap={8} align="center" wrap>
                      <Text>{commit.subject}</Text>
                      <Text size="small" tone="tertiary">
                        {commit.author} · {commit.date.slice(0, 10)}
                      </Text>
                    </Row>
                    {expanded ? (
                      <Stack gap={6}>
                        <Text size="small" tone={commit.body ? "secondary" : "tertiary"}>
                          {commit.body || "No body"}
                        </Text>
                        <Row gap={8} align="center" wrap>
                          <Text size="small" tone="tertiary">
                            {commit.files} files
                          </Text>
                          <DiffStats
                            additions={commit.additions}
                            deletions={commit.deletions}
                          />
                          {commit.flags.map((flag) => (
                            <Pill key={flag} active>
                              {FLAG_LABEL[flag]}
                            </Pill>
                          ))}
                        </Row>
                      </Stack>
                    ) : null}
                  </div>
                </div>
              );
            })}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "76px 22px minmax(0, 1fr)",
                minWidth: 0,
              }}
            >
              <Text size="small" tone="tertiary">
                {BASE_SHA}
              </Text>
              <div
                aria-hidden="true"
                style={{
                  color: theme.text.tertiary,
                  marginLeft: 7,
                  position: "relative",
                }}
              >
                <span
                  style={{
                    background: theme.bg.editor,
                    border: "2px solid currentColor",
                    borderRadius: "50%",
                    display: "block",
                    height: 11,
                    left: -5,
                    position: "absolute",
                    top: 4,
                    width: 11,
                  }}
                />
              </div>
              <Text size="small" tone="secondary">
                Branched from {BASE}
              </Text>
            </div>
          </Stack>
        ) : (
          <Text tone="secondary">No commits against {BASE}.</Text>
        )
      ) : current ? (
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(220px, 280px) minmax(0, 1fr)",
          gap: 16,
          alignItems: "start",
        }}
      >
        <Stack gap={4}>
          <Text size="small" tone="tertiary">
            {visible.length === FILES.length
              ? `${FILES.length} files`
              : `${visible.length} of ${FILES.length} files`}
          </Text>
          {visible.length === 0 ? (
            <Row gap={8} align="center">
              <Text size="small" tone="secondary">
                No files match.
              </Text>
              <Button
                variant="ghost"
                onClick={() => {
                  setStatusFilter("all");
                  setReviewFilter("none");
                  setQuery("");
                }}
              >
                Clear filters
              </Button>
            </Row>
          ) : null}
          {visible.map((file) => (
            <div key={file.path}>
              <Row gap={6} align="center">
                <Checkbox
                  checked={isReviewed(file)}
                  onChange={(checked) =>
                    markReviewed(file.path, file.digest, checked)
                  }
                />
                <Button
                  variant={file.path === current.path ? "secondary" : "ghost"}
                  onClick={() => setSelected(file.path)}
                >
                  {fileName(file.path)}
                </Button>
                <Spacer />
                <DiffStats additions={file.additions} deletions={file.deletions} />
              </Row>
            </div>
          ))}
        </Stack>

        <Stack gap={10}>
          <Card>
            <CardHeader
              trailing={
                <DiffStats additions={current.additions} deletions={current.deletions} />
              }
            >
              {current.path}
            </CardHeader>
            <CardBody style={{ padding: 0 }}>
              <DiffView path={current.path} lines={lines} />
            </CardBody>
          </Card>
          <Row gap={8} align="center" wrap>
            <Button
              variant="primary"
              onClick={() => dispatch({ type: "openFile", path: current.path })}
            >
              Open file
            </Button>
            <Checkbox
              checked={isReviewed(current)}
              onChange={(checked) =>
                markReviewed(current.path, current.digest, checked)
              }
              label="Reviewed"
            />
            <Text size="small" tone="tertiary">
              {current.status}
            </Text>
          </Row>
          <Text size="small" tone="secondary">
            Notes stay on this canvas. They are not committed or posted.
          </Text>
          <TextArea
            rows={3}
            value={notes[current.path] ?? ""}
            onChange={(value) => setNotes({ ...notes, [current.path]: value })}
            placeholder="Your notes on this file…"
          />
        </Stack>
      </div>
      ) : (
        <Text tone="secondary">No diff against {BASE}.</Text>
      )}
    </Stack>
  );
}
