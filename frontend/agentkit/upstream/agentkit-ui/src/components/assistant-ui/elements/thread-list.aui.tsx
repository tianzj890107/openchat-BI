"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import {
  groupThreadIndices,
  isPinnedCustom,
  type ThreadListGroup,
} from "@/components/assistant-ui/elements/thread-list-groups";
import { cn } from "@/lib/utils";
import {
  AuiIf,
  ThreadListItemMorePrimitive,
  ThreadListItemPrimitive,
  ThreadListPrimitive,
  useAui,
  useAuiState,
} from "@assistant-ui/react";
import {
  ArchiveIcon,
  Loader2Icon,
  MoreHorizontalIcon,
  PencilIcon,
  PinIcon,
  PinOffIcon,
  PlusIcon,
  SearchIcon,
  TrashIcon,
} from "lucide-react";
import {
  createContext,
  createElement,
  forwardRef,
  Fragment,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentPropsWithoutRef,
  type ComponentType,
  type FC,
} from "react";

export const ThreadList: FC = () => {
  const [search, setSearch] = useState("");
  const hasThreads = useAuiState((s) => s.threads.threadIds.length > 0);

  return (
    <ThreadListRoot>
      <ThreadListNew />
      {hasThreads && (
        <ThreadListSearch value={search} onValueChange={setSearch} />
      )}
      <ThreadListItems searchQuery={hasThreads ? search : ""} />
    </ThreadListRoot>
  );
};

export const ThreadListSearch = forwardRef<
  HTMLInputElement,
  Omit<ComponentPropsWithoutRef<typeof Input>, "value" | "onChange"> & {
    value: string;
    onValueChange: (value: string) => void;
  }
>(({ className, value, onValueChange, ...props }, ref) => {
  return (
    <div data-slot="aui_thread-list-search" className="relative px-0.5 py-1">
      <SearchIcon
        data-slot="aui_thread-list-search-icon"
        className="text-muted-foreground pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2"
      />
      <Input
        ref={ref}
        type="search"
        value={value}
        onChange={(event) => onValueChange(event.target.value)}
        aria-label="搜索会话"
        placeholder="搜索会话"
        className={cn("h-8 ps-8 text-sm", className)}
        {...props}
      />
    </div>
  );
});

ThreadListSearch.displayName = "ThreadListSearch";

export const ThreadListRoot: FC<
  ComponentPropsWithoutRef<typeof ThreadListPrimitive.Root>
> = ({ className, ...props }) => {
  return (
    <ThreadListPrimitive.Root
      data-slot="aui_thread-list-root"
      className={cn("flex flex-col gap-0.5", className)}
      {...props}
    />
  );
};

/** Optional per-item trailing badge (e.g. a status read from the item's custom metadata). */
const ThreadListItemBadgeContext = createContext<ComponentType | null>(null);

/** Optional per-item secondary line under the title (renders nothing to stay single-line). */
const ThreadListItemSubtitleContext = createContext<ComponentType | null>(null);

export type ThreadListDeleteDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

/**
 * Optional per-item delete confirmation (e.g. choosing what happens to the
 * thread's artifacts). Rendered outside the menu, so it survives the menu
 * closing; it runs inside the item's scope and should call
 * `aui.threadListItem.delete()` itself.
 */
const ThreadListItemDeleteDialogContext =
  createContext<ComponentType<ThreadListDeleteDialogProps> | null>(null);

/** Which optional item actions the hosting adapter actually supports. */
const ThreadListItemActionsContext = createContext<{
  archivable: boolean;
  pinnable: boolean;
}>({ archivable: true, pinnable: false });

export const ThreadListItems: FC<
  ComponentPropsWithoutRef<"div"> & {
    searchQuery?: string;
    itemBadge?: ComponentType | undefined;
    itemSubtitle?: ComponentType | undefined;
    deleteDialog?: ComponentType<ThreadListDeleteDialogProps> | undefined;
    /** Show「归档」; turn off when the adapter's archive is a no-op. */
    archivable?: boolean;
    /** Show「置顶 / 取消置顶」; requires the adapter to implement `updateCustom`. */
    pinnable?: boolean;
  }
> = ({
  className,
  searchQuery = "",
  itemBadge,
  itemSubtitle,
  deleteDialog,
  archivable = true,
  pinnable = false,
  ...props
}) => {
  const actions = useMemo(
    () => ({ archivable, pinnable }),
    [archivable, pinnable],
  );
  return (
    <ThreadListItemBadgeContext.Provider value={itemBadge ?? null}>
      <ThreadListItemSubtitleContext.Provider value={itemSubtitle ?? null}>
      <ThreadListItemDeleteDialogContext.Provider value={deleteDialog ?? null}>
        <ThreadListItemActionsContext.Provider value={actions}>
          <div
            data-slot="aui_thread-list-items"
            className={cn("flex flex-col gap-0.5", className)}
            {...props}
          >
            <AuiIf condition={(s) => s.threads.isLoading}>
              <ThreadListSkeleton />
            </AuiIf>
            <AuiIf condition={(s) => !s.threads.isLoading}>
              <ThreadListItemGroups searchQuery={searchQuery} />
            </AuiIf>
          </div>
        </ThreadListItemActionsContext.Provider>
      </ThreadListItemDeleteDialogContext.Provider>
      </ThreadListItemSubtitleContext.Provider>
    </ThreadListItemBadgeContext.Provider>
  );
};

export type { ThreadListGroup };

/**
 * Filters the thread list by title and buckets the matches with
 * `groupThreadIndices`. `groups` is null when no thread is pinned or dated,
 * in which case `filteredIndices` keeps the runtime order.
 */
export const useThreadListGroups = (searchQuery = "") => {
  const threadIds = useAuiState((s) => s.threads.threadIds);
  const threadItems = useAuiState((s) => s.threads.threadItems);

  const query = searchQuery.trim().toLowerCase();

  return useMemo(() => {
    const itemsById = new Map(threadItems.map((item) => [item.id, item]));
    const dates = threadIds.map((id) => itemsById.get(id)?.lastMessageAt);
    const pinned = threadIds.map((id) =>
      isPinnedCustom(itemsById.get(id)?.custom),
    );
    const filteredIndices = threadIds
      .map((id, index) => ({ id, index }))
      .filter(
        ({ id }) =>
          !query ||
          (itemsById.get(id)?.title || "新会话").toLowerCase().includes(query),
      )
      .map(({ index }) => index);
    const groups = groupThreadIndices(
      filteredIndices,
      dates,
      pinned,
      new Date(),
    );
    return { threadIds, filteredIndices, groups };
  }, [threadIds, threadItems, query]);
};

/** 「加载更早的会话」：仅在 adapter 返回了 nextCursor 时出现。 */
export const ThreadListLoadMore: FC<{ className?: string }> = ({
  className,
}) => {
  const hasMore = useAuiState((s) => s.threads.hasMore);
  const isLoadingMore = useAuiState((s) => s.threads.isLoadingMore);
  if (!hasMore) return null;
  return (
    <ThreadListPrimitive.LoadMore asChild>
      <Button
        variant="ghost"
        data-slot="aui_thread-list-load-more"
        disabled={isLoadingMore}
        className={cn(
          "text-muted-foreground hover:bg-muted h-8 justify-start gap-2 rounded-md px-2.5 text-xs font-normal",
          className,
        )}
      >
        {isLoadingMore && <Spinner className="size-3.5" />}
        加载更早的会话
      </Button>
    </ThreadListPrimitive.LoadMore>
  );
};

const ThreadListItemGroups: FC<{ searchQuery?: string }> = ({
  searchQuery = "",
}) => {
  const { threadIds, filteredIndices, groups } =
    useThreadListGroups(searchQuery);
  const hasMore = useAuiState((s) => s.threads.hasMore);
  const query = searchQuery.trim();

  if (query && filteredIndices.length === 0) {
    return (
      <>
        <div
          data-slot="aui_thread-list-empty"
          className="text-muted-foreground px-2.5 py-4 text-sm"
        >
          {hasMore ? "已加载的会话中没有匹配项" : "没有匹配的会话"}
        </div>
        <ThreadListLoadMore />
      </>
    );
  }

  if (!groups) {
    return (
      <>
        {filteredIndices.map((index) => (
          <ThreadListPrimitive.ItemByIndex
            key={threadIds[index]}
            index={index}
            components={{ ThreadListItem }}
          />
        ))}
        <ThreadListLoadMore />
      </>
    );
  }

  return (
    <>
      {groups.map((group) => (
        <Fragment key={group.label}>
          <div
            data-slot="aui_thread-list-group-label"
            className="text-muted-foreground px-2.5 pt-3 pb-1 text-xs font-medium"
          >
            {group.label}
          </div>
          {group.indices.map((index) => (
            <ThreadListPrimitive.ItemByIndex
              key={threadIds[index]}
              index={index}
              components={{ ThreadListItem }}
            />
          ))}
        </Fragment>
      ))}
      <ThreadListLoadMore />
    </>
  );
};

export const ThreadListNew = forwardRef<
  HTMLButtonElement,
  ComponentPropsWithoutRef<typeof Button> & { labelClassName?: string }
>(({ className, labelClassName, children, ...props }, ref) => {
  return (
    <ThreadListPrimitive.New asChild>
      <Button
        ref={ref}
        variant="ghost"
        data-slot="aui_thread-list-new"
        className={cn(
          "hover:bg-muted data-active:bg-muted h-8 justify-start gap-2 rounded-md px-2.5 text-sm font-normal",
          className,
        )}
        {...props}
      >
        {children ?? (
          <>
            <PlusIcon
              data-slot="aui_thread-list-new-icon"
              className="size-4 shrink-0"
            />
            <span
              data-slot="aui_thread-list-new-label"
              className={cn("whitespace-nowrap", labelClassName)}
            >
              新建会话
            </span>
          </>
        )}
      </Button>
    </ThreadListPrimitive.New>
  );
});

ThreadListNew.displayName = "ThreadListNew";

const ThreadListSkeleton: FC = () => {
  return (
    <div className="flex flex-col gap-0.5">
      {Array.from({ length: 5 }, (_, i) => (
        <div
          key={i}
          role="status"
          aria-label="正在加载会话"
          data-slot="aui_thread-list-skeleton-wrapper"
          className="flex h-8 items-center px-2.5"
        >
          <Skeleton
            data-slot="aui_thread-list-skeleton"
            className="h-3.5 w-full"
          />
        </div>
      ))}
    </div>
  );
};

export const ThreadListItem: FC = () => {
  const isRunning = useAuiState((s) => s.threadListItem.isRunning);
  const ItemBadge = useContext(ThreadListItemBadgeContext);
  const ItemSubtitle = useContext(ThreadListItemSubtitleContext);
  const [isRenaming, setIsRenaming] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const restoreFocusRef = useRef(false);

  useEffect(() => {
    if (isRenaming || !restoreFocusRef.current) return;
    restoreFocusRef.current = false;
    triggerRef.current?.focus();
  }, [isRenaming]);

  return (
    <ThreadListItemPrimitive.Root
      data-slot="aui_thread-list-item"
      className="group hover:bg-muted focus-visible:bg-muted data-active:bg-muted has-focus-visible:bg-muted has-data-[state=open]:bg-muted relative flex min-h-8 items-center rounded-md transition-colors focus-visible:outline-none"
    >
      {isRenaming ? (
        <ThreadListItemRename
          onDone={(restoreFocus) => {
            restoreFocusRef.current = restoreFocus;
            setIsRenaming(false);
          }}
        />
      ) : (
        <ThreadListItemPrimitive.Trigger
          ref={triggerRef}
          data-slot="aui_thread-list-item-trigger"
          className="focus-visible:ring-ring/50 flex min-w-0 flex-1 items-center self-stretch rounded-md px-2.5 py-1 text-start text-sm outline-none group-hover:pe-9 group-has-focus-visible:pe-9 group-has-data-[state=open]:pe-9 group-data-active:pe-9 focus-visible:ring-1"
        >
          {isRunning && (
            <Loader2Icon
              aria-hidden
              data-slot="aui_thread-list-item-running"
              className="text-muted-foreground me-1.5 size-3.5 shrink-0 animate-spin"
            />
          )}
          <span className="flex min-w-0 flex-1 flex-col">
            <span
              data-slot="aui_thread-list-item-title"
              className="min-w-0 truncate"
            >
              <ThreadListItemPrimitive.Title fallback="新会话" />
            </span>
            {ItemSubtitle ? createElement(ItemSubtitle) : null}
          </span>
          {ItemBadge ? createElement(ItemBadge) : null}
          {isRunning && <span className="sr-only">运行中</span>}
        </ThreadListItemPrimitive.Trigger>
      )}
      <ThreadListItemMore onRename={() => setIsRenaming(true)} />
    </ThreadListItemPrimitive.Root>
  );
};

const ThreadListItemRename: FC<{
  onDone: (restoreFocus: boolean) => void;
}> = ({ onDone }) => {
  const aui = useAui();
  const title = useAuiState((s) => s.threadListItem.title) ?? "";
  const [value, setValue] = useState(title);
  const inputRef = useRef<HTMLInputElement>(null);
  const settledRef = useRef(false);

  useEffect(() => {
    inputRef.current?.select();
  }, []);

  const commit = (restoreFocus: boolean) => {
    if (settledRef.current) return;
    settledRef.current = true;

    const next = value.trim();
    if (!next || next === title) {
      onDone(restoreFocus);
      return;
    }

    // Deferred so a synchronous throw lands on the rejection path too.
    Promise.resolve()
      .then(() => aui.threadListItem.rename(next))
      .then(
        () => onDone(restoreFocus),
        () => {
          settledRef.current = false;
          if (restoreFocus) inputRef.current?.focus();
        },
      );
  };

  const cancel = () => {
    if (settledRef.current) return;
    settledRef.current = true;
    onDone(true);
  };

  return (
    <Input
      ref={inputRef}
      autoFocus
      data-slot="aui_thread-list-item-rename"
      aria-label="重命名会话"
      value={value}
      className="h-7 min-w-0 flex-1 ps-2.5 pe-9 text-sm"
      onChange={(event) => setValue(event.target.value)}
      onBlur={() => commit(false)}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          commit(true);
        } else if (event.key === "Escape") {
          event.preventDefault();
          cancel();
        }
      }}
    />
  );
};

const ThreadListItemPinItem: FC = () => {
  const aui = useAui();
  const custom = useAuiState((s) => s.threadListItem.custom);
  const pinned = isPinnedCustom(custom);
  return (
    <ThreadListItemMorePrimitive.Item
      data-slot="aui_thread-list-item-more-item"
      className="hover:bg-accent hover:text-accent-foreground focus:bg-accent focus:text-accent-foreground flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm outline-none select-none"
      onSelect={() => {
        const { pinned: _pinned, ...rest } = custom ?? {};
        aui.threadListItem.updateCustom(
          pinned ? rest : { ...rest, pinned: true },
        );
      }}
    >
      {pinned ? (
        <PinOffIcon className="size-4" />
      ) : (
        <PinIcon className="size-4" />
      )}
      {pinned ? "取消置顶" : "置顶"}
    </ThreadListItemMorePrimitive.Item>
  );
};

const ThreadListItemMore: FC<{ onRename: () => void }> = ({ onRename }) => {
  const DeleteDialog = useContext(ThreadListItemDeleteDialogContext);
  const { archivable, pinnable } = useContext(ThreadListItemActionsContext);
  const [deleteOpen, setDeleteOpen] = useState(false);
  // The closing menu keeps trapping focus while it animates out and then
  // restores focus to its trigger; that would blur the rename input or dismiss
  // a freshly opened dialog. Run such actions only once the menu has closed.
  const afterCloseRef = useRef<(() => void) | null>(null);
  const runAfterClose = (action: () => void) => {
    afterCloseRef.current = action;
  };

  return (
    <>
      <ThreadListItemMorePrimitive.Root sharedFocusGroup>
        <ThreadListItemMorePrimitive.Trigger asChild>
          <Button
            variant="ghost"
            size="icon"
            data-slot="aui_thread-list-item-more"
            className="data-[state=open]:bg-accent absolute end-1.5 top-1/2 size-6 -translate-y-1/2 p-0 opacity-0 group-hover:opacity-100 group-has-focus-visible:opacity-100 group-data-active:opacity-100 data-[state=open]:opacity-100"
          >
            <MoreHorizontalIcon className="size-3.5" />
            <span className="sr-only">更多操作</span>
          </Button>
        </ThreadListItemMorePrimitive.Trigger>
        <ThreadListItemMorePrimitive.Content
          side="right"
          align="start"
          sideOffset={6}
          data-slot="aui_thread-list-item-more-content"
          className="bg-popover text-popover-foreground data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95 data-[state=open]:animate-in data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 data-[state=closed]:animate-out data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 z-50 min-w-32 overflow-hidden rounded-xl border p-1.5"
          onCloseAutoFocus={(event) => {
            const action = afterCloseRef.current;
            if (!action) return;
            afterCloseRef.current = null;
            event.preventDefault();
            action();
          }}
        >
          <ThreadListItemMorePrimitive.Item
            data-slot="aui_thread-list-item-more-item"
            className="hover:bg-accent hover:text-accent-foreground focus:bg-accent focus:text-accent-foreground flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm outline-none select-none"
            onSelect={() => runAfterClose(onRename)}
          >
            <PencilIcon className="size-4" />
            重命名
          </ThreadListItemMorePrimitive.Item>
          {pinnable && <ThreadListItemPinItem />}
          {archivable && (
            <ThreadListItemPrimitive.Archive asChild>
              <ThreadListItemMorePrimitive.Item
                data-slot="aui_thread-list-item-more-item"
                className="hover:bg-accent hover:text-accent-foreground focus:bg-accent focus:text-accent-foreground flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm outline-none select-none"
              >
                <ArchiveIcon className="size-4" />
                归档
              </ThreadListItemMorePrimitive.Item>
            </ThreadListItemPrimitive.Archive>
          )}
          {DeleteDialog ? (
            <ThreadListItemMorePrimitive.Item
              data-slot="aui_thread-list-item-more-item"
              className={DELETE_ITEM_CLASS}
              onSelect={() => runAfterClose(() => setDeleteOpen(true))}
            >
              <TrashIcon className="size-4" />
              删除
            </ThreadListItemMorePrimitive.Item>
          ) : (
            <ThreadListItemPrimitive.Delete asChild>
              <ThreadListItemMorePrimitive.Item
                data-slot="aui_thread-list-item-more-item"
                className={DELETE_ITEM_CLASS}
              >
                <TrashIcon className="size-4" />
                删除
              </ThreadListItemMorePrimitive.Item>
            </ThreadListItemPrimitive.Delete>
          )}
        </ThreadListItemMorePrimitive.Content>
      </ThreadListItemMorePrimitive.Root>
      {DeleteDialog
        ? createElement(DeleteDialog, {
            open: deleteOpen,
            onOpenChange: setDeleteOpen,
          })
        : null}
    </>
  );
};

const DELETE_ITEM_CLASS =
  "text-destructive hover:bg-destructive/10 hover:text-destructive focus:bg-destructive/10 focus:text-destructive flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm outline-none select-none";
