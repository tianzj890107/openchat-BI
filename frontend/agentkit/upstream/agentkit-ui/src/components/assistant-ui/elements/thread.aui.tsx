"use client";

import {
  ComposerAttachments,
  UserMessageAttachments,
} from "@/components/assistant-ui/elements/attachment.aui";
import { File } from "@/components/assistant-ui/elements/file";
import { AppFileIcon } from "@/components/file-icon";
import { ThreadFollowupSuggestions } from "@/components/assistant-ui/elements/follow-up-suggestions.aui";
import { Image } from "@/components/assistant-ui/elements/image";
import { GenerationLoader } from "@/components/assistant-ui/elements/loading-state";
import { MarkdownText } from "@/components/assistant-ui/elements/markdown-text";
import {
  Reasoning,
  ReasoningContent,
  ReasoningRoot,
  ReasoningText,
  ReasoningTrigger,
} from "@/components/assistant-ui/elements/reasoning.aui";
import { SemanticToolFallback } from "@/components/assistant-ui/elements/semantic-tool-fallback.aui";
import {
  ToolGroupContent,
  ToolGroupRoot,
  ToolGroupTrigger,
} from "@/components/assistant-ui/elements/tool-group.aui";
import { MessageTiming } from "@/components/assistant-ui/elements/message-timing.aui";
import {
  actionIconButton,
  floating,
  iconSwap,
  iconSwapIn,
  iconSwapOut,
} from "@/components/assistant-ui/elements/surfaces";
import { TooltipIconButton } from "@/components/assistant-ui/elements/tooltip-icon-button";
import { ComposerSlash } from "@/components/assistant-ui/slash-commands/composer-slash";
import { ComposerMention } from "@/components/assistant-ui/slash-commands/composer-mention";
import type {
  SkillCommand,
  SlashCommandDef,
  ThreadComposerOptions,
} from "@/components/assistant-ui/slash-commands/types";
import { appendSkillDirective } from "@/components/assistant-ui/slash-commands/use-composer-slash";
import { resolveSlashIcon } from "@/components/assistant-ui/slash-commands/icons";
import { createDirectiveText } from "@/components/assistant-ui/elements/directive-text.aui";
import {
  ComposerInputRefContext,
  useComposerInputRef,
} from "@/components/assistant-ui/utils/composer-input-ref";
import {
  focusPlaceholder,
  handlePlaceholderTab,
  hasPlaceholders,
} from "@/components/assistant-ui/utils/placeholders";
import { ComposerAttachmentMenu } from "@/components/assistant-ui/elements/composer-attachment-menu";
import {
  filesFromDataTransfer,
  hasDirectory,
} from "@/components/assistant-ui/utils/relative-path";
import {
  ThreadComposerContext,
  useComposerCommands,
  useNewThreadAction,
  useThreadComposerOptions,
} from "@/components/assistant-ui/slash-commands/use-composer-commands";
import {
  MAX_QUEUE,
  useComposerQueueControl,
} from "@/components/assistant-ui/elements/composer-queue-control";
import { Button } from "@/components/ui/button";
import {
  briefLine,
  classifyPart,
  decisionWord,
  isLiveFileWrite,
  isUserFacingTool,
  minimalPlaceholder,
  PROCESS_COPY,
  summaryLine,
  type LoosePart,
  type ProcessDetail,
} from "@/features/agent-shell/process-detail";
import { useTurnProcessDuration } from "@/features/agent-shell/use-turn-process-duration";
import { useUserProcessDetail } from "@/features/agent-shell/process-detail-pref";
import { TurnArtifacts } from "@/features/agent-artifact/turn-artifacts";
import { TurnFileChanges } from "@/features/assistant/file-changes/turn-file-changes";
import { GrowthTurnFooter } from "@/features/assistant/growth/growth-turn-footer";
import { PromptAnswerContext } from "@/features/agent-generative-surface/prompt-answer-context";
import { messagePartsToMarkdown } from "@/features/agent-generative-surface/lib/tree-to-markdown";
import {
  generativeRejection,
  isPendingPromptUser,
  promptSurfaceLabel,
  promptSurfaceState,
  promptSurfaceSummary,
  promptUserSubmitInput,
  promptUserCanSubmit,
  promptUserOutcome,
  type PromptUserMessagePart,
} from "@/features/agent-generative-surface/prompt-user-ready";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { copyText } from "@/lib/clipboard";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import {
  ActionBarMorePrimitive,
  ActionBarPrimitive,
  AuiIf,
  type AssistantState,
  BranchPickerPrimitive,
  ComposerPrimitive,
  defaultDirectiveFormatter,
  ErrorPrimitive,
  groupPartByType,
  MessagePrimitive,
  QueueItemPrimitive,
  SuggestionPrimitive,
  ThreadPrimitive,
  useMessageTiming,
  type FileMessagePartComponent,
  type ImageMessagePartComponent,
  type ToolCallMessagePartComponent,
  useAui,
  useAuiEvent,
  useAuiState,
  useScrollLock,
} from "@assistant-ui/react";
import {
  ArrowDownIcon,
  ArrowUpIcon,
  CheckIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  CopyIcon,
  DownloadIcon,
  MicIcon,
  MoreHorizontalIcon,
  PaperclipIcon,
  PencilIcon,
  PlusIcon,
  RefreshCwIcon,
  SkipForwardIcon,
  SlashIcon,
  SquareIcon,
  SquarePenIcon,
  ThumbsDownIcon,
  ThumbsUpIcon,
} from "lucide-react";
import { WandSparklesIcon } from "@/components/icons/keyline";
import { useReducedMotionConfig } from "motion/react";
import {
  createContext,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
  type FC,
  type MouseEvent,
  type PropsWithChildren,
  type ReactNode,
} from "react";

export type ThreadGroupPart = MessagePrimitive.GroupedParts.GroupPart;

/**
 * Optional component overrides for the thread. `AssistantMessage` and
 * `Welcome` replace whole sections; the remaining slots override how the
 * assistant message renders tool calls and part groups. Tool UIs registered
 * by name (toolkit `render`, `useAssistantDataUI`) take precedence over
 * `ToolFallback`. When `TaskGroup` is set, tool calls that carry a nested
 * conversation and have no registered UI render through it instead of the
 * tool group; without it they render like any other tool call.
 */
export type ThreadComponents = {
  AssistantMessage?: ComponentType | undefined;
  Welcome?: ComponentType | undefined;
  /** Replaces the composer (e.g. a structured start form or a read-only notice). */
  Composer?: ComponentType<{ autoFocus: boolean }> | undefined;
  ToolFallback?: ToolCallMessagePartComponent | undefined;
  ToolGroup?:
    | ComponentType<PropsWithChildren<{ group: ThreadGroupPart }>>
    | undefined;
  ReasoningGroup?:
    | ComponentType<PropsWithChildren<{ group: ThreadGroupPart }>>
    | undefined;
  TaskGroup?: ComponentType<{ group: ThreadGroupPart }> | undefined;
  /** Rendered after each message inside its message scope (e.g. a context-change marker). */
  MessageAfter?: ComponentType | undefined;
};

const messageGroupBy = groupPartByType({
  reasoning: ["group-chainOfThought", "group-reasoning"],
  "tool-call": ["group-chainOfThought", "group-tool"],
  "standalone-tool-call": [],
});

type ThreadGroupKey =
  | "group-chainOfThought"
  | "group-reasoning"
  | "group-tool"
  | "group-task"
  | "group-generative";

const TASK_GROUP_PATH: readonly ThreadGroupKey[] = [
  "group-chainOfThought",
  "group-task",
];

const taskAwareGroupBy = (
  part: Parameters<typeof messageGroupBy>[0],
  context?: Parameters<typeof messageGroupBy>[1],
): readonly ThreadGroupKey[] => {
  const path = messageGroupBy(part, context);
  return part.type === "tool-call" &&
    (part.toolName === "task" || part.messages !== undefined) &&
    path.length > 0 &&
    !context?.toolUIs?.[part.toolName]?.length
    ? TASK_GROUP_PATH
    : path;
};

const isPresentTool = (
  part: Parameters<typeof messageGroupBy>[0],
): boolean => part.type === "tool-call" && part.toolName === "present";

const isPromptUserTool = (
  part: Parameters<typeof messageGroupBy>[0],
): boolean => part.type === "tool-call" && part.toolName === "promptUser";

const isBoundaryAskPrompt = (part: PromptUserMessagePart): boolean => {
  const args = (part as { args?: unknown }).args;
  return (
    typeof args === "object" &&
    args !== null &&
    (args as { _type?: unknown })._type === "BoundaryAsk"
  );
};

const findScrollableAncestor = (element: HTMLElement | null) => {
  let current = element;
  while (current) {
    const { overflowY } = getComputedStyle(current);
    if (overflowY === "scroll" || overflowY === "auto") return current;
    current = current.parentElement;
  }
  return null;
};

const HITL_SCROLL_LOCK_MS = 800;
const HITL_SUBMIT_SELECTOR =
  "[data-aui=card-confirm], [data-aui=card-cancel], [data-aui=button], [data-aui-submit], [type=submit], [type=reset]";

const GenerativeSurface: FC<{
  kind?: "present" | "prompt";
  busy?: boolean;
  pending?: boolean;
  outcome?: "submit" | "cancel" | null;
  submitInput?: Record<string, unknown> | null;
  /** The card renders its own read-only receipt (BoundaryAsk), so it stays open once answered. */
  inlineReceipt?: boolean;
  children: ReactNode;
}> = ({
  kind = "present",
  busy,
  pending = false,
  outcome = null,
  submitInput = null,
  inlineReceipt = false,
  children,
}) => {
  const ref = useRef<HTMLDivElement>(null);
  const [showAnswered, setShowAnswered] = useState(false);
  const lockScroll = useScrollLock(ref, HITL_SCROLL_LOCK_MS);
  const savedTop = useRef<number | null>(null);
  const wasPending = useRef(pending);
  const freezeTimer = useRef(0);
  const promptState =
    kind === "prompt"
      ? promptSurfaceState({
          pending,
          ready: Boolean(pending && !busy),
          outcome,
        })
      : null;
  const answered = promptState === "submitted" || promptState === "cancelled";
  // BoundaryAsk keeps its own receipt in place; other trees fold to a summary line.
  const collapsible = answered && !inlineReceipt;
  const summary =
    collapsible && promptState === "submitted"
      ? promptSurfaceSummary(submitInput)
      : null;
  const answer = useMemo(
    () => (promptState ? { state: promptState, input: submitInput } : null),
    [promptState, submitInput],
  );

  const freezeScroller = (scroller: HTMLElement) => {
    scroller.style.scrollBehavior = "auto";
    window.clearTimeout(freezeTimer.current);
    freezeTimer.current = window.setTimeout(() => {
      scroller.style.removeProperty("scroll-behavior");
    }, HITL_SCROLL_LOCK_MS);
  };

  const captureAndLock = () => {
    const scroller = findScrollableAncestor(ref.current);
    if (scroller) {
      savedTop.current = scroller.scrollTop;
      freezeScroller(scroller);
    }
    lockScroll();
  };

  const restoreAndLock = () => {
    const scroller = findScrollableAncestor(ref.current);
    if (scroller && savedTop.current != null) {
      freezeScroller(scroller);
      scroller.scrollTop = savedTop.current;
    }
    lockScroll();
  };

  useLayoutEffect(() => {
    if (wasPending.current && !pending) restoreAndLock();
    wasPending.current = pending;
  }, [pending, lockScroll]);

  useEffect(() => () => window.clearTimeout(freezeTimer.current), []);

  useAuiEvent("thread.runStart", () => {
    if (savedTop.current == null) return;
    restoreAndLock();
    savedTop.current = null;
  });

  return (
    <div
      ref={ref}
      data-slot="aui_generative-surface"
      data-generative={kind}
      data-prompt-state={promptState ?? undefined}
      aria-busy={busy || undefined}
      onPointerDownCapture={
        pending
          ? (event) => {
              const target = event.target as HTMLElement | null;
              if (!target?.closest(HITL_SUBMIT_SELECTOR)) return;
              captureAndLock();
            }
          : undefined
      }
      onKeyDownCapture={
        pending
          ? (event) => {
              if (event.key !== "Enter" && event.key !== " ") return;
              captureAndLock();
            }
          : undefined
      }
      className={cn(
        "my-2 flex flex-col [overflow-anchor:auto]",
        // 提问卡的内边距由 generative-surface-skin.css 按界面风格提供。
        kind === "prompt" ? "gap-2" : "gap-4",
        "[&_fieldset[data-aui=answered]_[data-scene-enter]]:animate-none",
        busy && "pointer-events-none",
      )}
    >
      {promptState ? (
        <div data-slot="generative-prompt-status-row">
          <p data-slot="generative-prompt-status" aria-live="polite">
            {answered ? (
              promptState === "submitted" ? (
                <CheckIcon aria-hidden data-slot="generative-prompt-status-icon" />
              ) : (
                <SkipForwardIcon
                  aria-hidden
                  data-slot="generative-prompt-status-icon"
                />
              )
            ) : null}
            <span>
              {promptSurfaceLabel(promptState)}
              {summary ? ` · ${summary}` : ""}
            </span>
          </p>
          {collapsible ? (
            <button
              type="button"
              data-slot="generative-prompt-toggle"
              aria-expanded={showAnswered}
              onClick={() => setShowAnswered((open) => !open)}
            >
              {showAnswered ? "收起" : "查看"}
            </button>
          ) : null}
        </div>
      ) : null}
      {kind === "prompt" ? (
        <PromptAnswerContext.Provider value={answer}>
          <div
            data-slot="generative-prompt-body"
            data-collapsed={collapsible && !showAnswered ? "" : undefined}
          >
            {children}
          </div>
        </PromptAnswerContext.Provider>
      ) : (
        children
      )}
    </div>
  );
};

export type ThreadWelcomeCopy = {
  title?: string | undefined;
  message?: string | undefined;
};

export type ThreadProps = {
  components?: ThreadComponents | undefined;
  autoFocus?: boolean | undefined;
  composerPlaceholder?: string | undefined;
  welcome?: ThreadWelcomeCopy | undefined;
  allowAttachments?: boolean | undefined;
  /** 024：输入框模式相关选项；缺省继承外层 `ThreadComposerProvider`。 */
  composer?: ThreadComposerOptions | undefined;
  /**
   * 过程展示档位。缺省时读账号级展示偏好（038）；偏好也未设置则 `trace`，
   * 让观测会话等未显式传入的调用方保持现有密度。
   * 外壳与演示页显式传入；不从界面种类推断。
   */
  processDetail?: ProcessDetail | undefined;
};

/** 外壳渲染器 / 页面在 `Thread` 之外提供输入框选项（`Thread.composer` 逐项覆盖）。 */
export const ThreadComposerProvider = ThreadComposerContext.Provider;

const EMPTY_COMPONENTS: ThreadComponents = {};
const DEFAULT_COMPOSER_PLACEHOLDER = "Send a message...";
const DEFAULT_WELCOME: ThreadWelcomeCopy = {
  title: "How can I help you today?",
};

const ThreadComponentsContext =
  createContext<ThreadComponents>(EMPTY_COMPONENTS);

/** 供自定义 `components.Composer`（如个人助手）读取占位文案。 */
export const ComposerPlaceholderContext = createContext(
  DEFAULT_COMPOSER_PLACEHOLDER,
);
const WelcomeCopyContext = createContext<ThreadWelcomeCopy>(DEFAULT_WELCOME);
/** 供自定义 `components.Composer` 读取是否允许附件。 */
export const AllowAttachmentsContext = createContext(true);
const ProcessDetailContext = createContext<ProcessDetail>("trace");

/** 当前消息流的过程档位（工具 UI 据此决定是否露出排障信息）。 */
export const useThreadProcessDetail = (): ProcessDetail =>
  useContext(ProcessDetailContext);

/**
 * 助手消息操作栏的额外按钮（渲染在耗时之后、「更多」之前）。默认为空，
 * 由对话面按需注入元素（如个人助手调试模式的「本轮链路」）；元素在每条消息里渲染，
 * 组件内用 `useAuiState` 读到的是当前消息。
 */
export const AssistantMessageActionsSlot = createContext<ReactNode>(null);

/**
 * 点踩前的确认（如个人助手的补充弹窗），resolve 为 true 才把消息记为「踩」。
 * 官方 `submitFeedback` 一调用就写入 `submittedFeedback` 且无法清除，
 * 不经确认直接提交的话，用户取消弹窗后按钮会停在已踩。未提供时走官方原语。
 */
export const NegativeFeedbackRequest = createContext<
  ((messageId: string) => Promise<boolean>) | null
>(null);

// Startup exposes a loading placeholder thread; treat it as a new chat so
// the composer mounts centered. Loads after startup keep the docked layout.
const isNewChatView = (s: AssistantState) =>
  s.thread.messages.length === 0 &&
  (!s.thread.isLoading || s.threads.isLoading);

// A switched thread that is still fetching its history: skeleton, not welcome.
const isHistoryLoadingView = (s: AssistantState) =>
  s.thread.messages.length === 0 &&
  s.thread.isLoading &&
  !s.thread.isDisabled &&
  !s.threads.isLoading;

const ThreadHistorySkeleton: FC = () => (
  <div
    data-slot="aui_thread-history-skeleton"
    role="status"
    className="animate-in fade-in fill-mode-both flex flex-col gap-y-6 [animation-delay:150ms] [animation-duration:200ms]"
  >
    <span className="sr-only">Loading conversation</span>
    <Skeleton className="ml-auto h-9 w-2/5 rounded-xl motion-reduce:animate-none" />
    <div className="flex flex-col gap-y-2">
      <Skeleton className="h-4 w-11/12 motion-reduce:animate-none" />
      <Skeleton className="h-4 w-4/5 motion-reduce:animate-none" />
      <Skeleton className="h-4 w-3/5 motion-reduce:animate-none" />
    </div>
    <Skeleton className="ml-auto h-9 w-1/3 rounded-xl motion-reduce:animate-none" />
    <div className="flex flex-col gap-y-2">
      <Skeleton className="h-4 w-10/12 motion-reduce:animate-none" />
      <Skeleton className="h-4 w-2/3 motion-reduce:animate-none" />
    </div>
  </div>
);

export const Thread: FC<ThreadProps> = ({
  components = EMPTY_COMPONENTS,
  autoFocus = true,
  composerPlaceholder = DEFAULT_COMPOSER_PLACEHOLDER,
  welcome = DEFAULT_WELCOME,
  allowAttachments = true,
  composer,
  processDetail,
}) => {
  const isEmpty = useAuiState(isNewChatView);
  const inherited = useThreadComposerOptions();
  // 显式传入 > 账号级偏好 > 现状默认（观测会话仍按调用方显式传 trace）。
  const userDetail = useUserProcessDetail();
  const detail = processDetail ?? userDetail ?? "trace";
  const composerOptions = useMemo(
    () => (composer ? { ...inherited, ...composer } : inherited),
    [inherited, composer],
  );
  const inputRef = useRef<HTMLTextAreaElement>(null);

  return (
    <ThreadComposerContext.Provider value={composerOptions}>
    <ComposerInputRefContext.Provider value={inputRef}>
    <ComposerPlaceholderContext.Provider value={composerPlaceholder}>
      <WelcomeCopyContext.Provider value={welcome}>
        <AllowAttachmentsContext.Provider value={allowAttachments}>
          <ProcessDetailContext.Provider value={detail}>
            <ThreadComponentsContext.Provider value={components}>
              <ThreadRoot isEmpty={isEmpty} autoFocus={autoFocus} />
            </ThreadComponentsContext.Provider>
          </ProcessDetailContext.Provider>
        </AllowAttachmentsContext.Provider>
      </WelcomeCopyContext.Provider>
    </ComposerPlaceholderContext.Provider>
    </ComposerInputRefContext.Provider>
    </ThreadComposerContext.Provider>
  );
};

const ThreadRoot: FC<{ isEmpty: boolean; autoFocus: boolean }> = ({
  isEmpty,
  autoFocus,
}) => {
  const { Welcome = ThreadWelcome, Composer: ComposerSlot = Composer } =
    useContext(ThreadComponentsContext);
  const { Approval } = useThreadComposerOptions();
  const processDetail = useContext(ProcessDetailContext);
  const viewportRef = useRef<HTMLDivElement>(null);

  // 发送消息时 assistant-ui 的 top-anchor 会调用
  // `viewport.scrollTo({ behavior: "smooth" })`（见 @assistant-ui/react 的
  // mountTopAnchorReserve），把新的一轮锚到视口顶部。这段平滑滚动持续约 250ms，
  // 期间上一条历史 AI 消息会在视口里连续滑动、兜底的「滚到底」按钮也会闪现一下，
  // 看起来就是发送后消息附近的「闪动」。CSS 的 scroll-smooth 关不掉它（JS 里显式
  // 传了 smooth），所以只让该视口的程序化平滑滚动瞬时到位；用户主动点击「滚到底」
  // 的滚动不受影响。
  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const nativeScrollTo = viewport.scrollTo as (
      options?: ScrollToOptions | number,
      y?: number,
    ) => void;
    viewport.scrollTo = ((
      options?: ScrollToOptions | number,
      y?: number,
    ) => {
      if (typeof options === "number") {
        nativeScrollTo.call(viewport, options, y ?? 0);
        return;
      }
      if (options?.behavior === "smooth") {
        nativeScrollTo.call(viewport, { ...options, behavior: "instant" });
        return;
      }
      nativeScrollTo.call(viewport, options);
    }) as typeof viewport.scrollTo;
    return () => {
      delete (viewport as { scrollTo?: unknown }).scrollTo;
    };
  }, []);

  return (
    <ThreadPrimitive.Root
      data-process-detail={processDetail}
      className="aui-root aui-thread-root bg-background @container flex h-full flex-col"
      style={{
        ["--thread-max-width" as string]: "44rem",
        ["--composer-bg" as string]: "var(--ui-composer-bg)",
        ["--composer-radius" as string]: "var(--ui-composer-radius)",
        ["--composer-padding" as string]: "8px",
      }}
    >
      <ThreadPrimitive.Viewport
        ref={viewportRef}
        turnAnchor="top"
        data-slot="aui_thread-viewport"
        className="relative flex flex-1 flex-col overflow-x-auto overflow-y-scroll scroll-smooth"
      >
        <div className="mx-auto flex w-full max-w-(--thread-max-width) flex-1 flex-col px-4 pt-4">
          {/* 内容列可居中；Footer 始终 mt-auto 钉底，避免打字卸建议时 Composer 下移 */}
          <div
            className={cn(
              "flex min-h-0 flex-1 flex-col",
              isEmpty && "justify-center",
            )}
          >
            <AuiIf condition={isNewChatView}>
              <Welcome />
            </AuiIf>
            <AuiIf condition={(s) => isNewChatView(s) && s.composer.isEmpty}>
              <ThreadSuggestions />
            </AuiIf>
            <AuiIf condition={isHistoryLoadingView}>
              <ThreadHistorySkeleton />
            </AuiIf>

            <div
              data-slot="aui_message-group"
              className="mb-14 flex flex-col gap-y-6 empty:hidden"
            >
              <ThreadPrimitive.Messages>
                {() => <ThreadMessage />}
              </ThreadPrimitive.Messages>
            </div>
          </div>

          <ThreadPrimitive.ViewportFooter
            className={cn(
              "aui-thread-viewport-footer bg-background sticky bottom-0 mt-auto flex flex-col gap-4 overflow-visible rounded-t-(--composer-radius) pb-4 md:pb-6",
            )}
          >
            <ThreadScrollToBottom />
            <ThreadFollowupSuggestions />
            {Approval ? <Approval /> : null}
            <ComposerSlot autoFocus={autoFocus} />
          </ThreadPrimitive.ViewportFooter>
        </div>
      </ThreadPrimitive.Viewport>
    </ThreadPrimitive.Root>
  );
};

const ThreadMessage: FC = () => {
  const { MessageAfter } = useContext(ThreadComponentsContext);
  if (!MessageAfter) return <ThreadMessageBody />;
  return (
    <>
      <ThreadMessageBody />
      <MessageAfter />
    </>
  );
};

const ThreadMessageBody: FC = () => {
  const { AssistantMessage: AssistantMessageComponent = AssistantMessage } =
    useContext(ThreadComponentsContext);
  const role = useAuiState((s) => s.message.role);
  const isEditing = useAuiState((s) => s.message.composer.isEditing);

  if (isEditing) return <EditComposer />;
  if (role === "user") return <UserMessage />;
  return <AssistantMessageComponent />;
};

const ThreadScrollToBottom: FC = () => {
  return (
    <ThreadPrimitive.ScrollToBottom asChild>
      <TooltipIconButton
        tooltip="Scroll to bottom"
        variant="outline"
        className="aui-thread-scroll-to-bottom dark:border-border dark:bg-background dark:hover:bg-accent absolute -top-12 z-10 self-center rounded-full p-4 disabled:invisible"
      >
        <ArrowDownIcon />
      </TooltipIconButton>
    </ThreadPrimitive.ScrollToBottom>
  );
};

const ThreadWelcome: FC = () => {
  const { title, message } = useContext(WelcomeCopyContext);
  return (
    <div className="aui-thread-welcome-root mb-6 flex flex-col items-center gap-2 px-4 text-center">
      {title ? (
        <h1 className="aui-thread-welcome-message-inner fade-in slide-in-from-bottom-1 animate-in fill-mode-both text-2xl font-medium tracking-tight duration-200">
          {title}
        </h1>
      ) : null}
      {message ? (
        <p className="aui-thread-welcome-message-detail text-muted-foreground max-w-prose text-base whitespace-pre-line">
          {message}
        </p>
      ) : null}
    </div>
  );
};

const ThreadSuggestions: FC = () => {
  return (
    <div
      data-slot="aui_thread-welcome-suggestions"
      className="aui-thread-welcome-suggestions flex w-full flex-wrap items-center justify-center gap-2 px-4"
    >
      <ThreadPrimitive.Suggestions>
        {() => <ThreadSuggestionItem />}
      </ThreadPrimitive.Suggestions>
    </div>
  );
};

const SUGGESTION_CLASS =
  "aui-thread-welcome-suggestion text-foreground hover:bg-muted border-divider h-auto gap-1.5 rounded-full border px-3.5 py-1.5 text-sm font-normal whitespace-nowrap transition-colors";

const ThreadSuggestionItem: FC = () => {
  const prompt = useAuiState((s) => s.suggestion.prompt);
  if (hasPlaceholders(prompt)) return <TemplateSuggestionItem prompt={prompt} />;
  return (
    <div className="aui-thread-welcome-suggestion-display fade-in slide-in-from-bottom-2 animate-in fill-mode-both duration-200">
      <SuggestionPrimitive.Trigger send asChild>
        <Button variant="ghost" className={SUGGESTION_CLASS}>
          <SuggestionPrimitive.Title className="aui-thread-welcome-suggestion-text-1" />
          <SuggestionPrimitive.Description className="aui-thread-welcome-suggestion-text-2 empty:hidden" />
        </Button>
      </SuggestionPrimitive.Trigger>
    </div>
  );
};

/** 含 `{{占位}}` 的推荐问题：填入输入框并选中第一个占位，让用户补全后再发送。 */
const TemplateSuggestionItem: FC<{ prompt: string }> = ({ prompt }) => {
  const aui = useAui();
  const inputRef = useComposerInputRef();
  return (
    <div className="aui-thread-welcome-suggestion-display fade-in slide-in-from-bottom-2 animate-in fill-mode-both duration-200">
      <Button
        variant="ghost"
        className={SUGGESTION_CLASS}
        onClick={() => {
          aui.composer().setText(prompt);
          requestAnimationFrame(() => focusPlaceholder(inputRef?.current));
        }}
      >
        <SuggestionPrimitive.Title className="aui-thread-welcome-suggestion-text-1" />
        <SuggestionPrimitive.Description className="aui-thread-welcome-suggestion-text-2 empty:hidden" />
      </Button>
    </div>
  );
};

/**
 * 统一输入框（024）：卡片自上而下为提示条、排队消息、附件预览、输入行、操作行。
 * 开发 / 预览 / 市场 / `/chatapp` 共用；模式差异只经 `ThreadComposerOptions` 注入。
 */
const Composer: FC<{ autoFocus: boolean }> = ({ autoFocus }) => {
  const placeholder = useContext(ComposerPlaceholderContext);
  const allowAttachments = useContext(AllowAttachmentsContext);
  const { Notice, mentions } = useThreadComposerOptions();
  const aui = useAui();
  const inputRef = useComposerInputRef();
  const shell = (
    <div
      data-slot="aui_composer-shell"
      onDropCapture={
        allowAttachments
          ? (e) => {
              // 拖入文件夹：展开为文件（附相对路径）后逐个加入；普通文件交给官方 dropzone。
              if (!hasDirectory(e.dataTransfer.items)) return;
              e.preventDefault();
              e.stopPropagation();
              void filesFromDataTransfer(e.dataTransfer.items).then((files) => {
                for (const file of files) void aui.composer().addAttachment(file);
              });
            }
          : undefined
      }
      className="border-composer-border shadow-composer data-[dragging=true]:border-ring focus-within:border-composer-border-focus flex w-full cursor-text flex-col gap-2 rounded-(--composer-radius) border bg-(--composer-bg) p-(--composer-padding) transition-[border-color] data-[dragging=true]:border-dashed data-[dragging=true]:bg-[color-mix(in_oklab,var(--color-accent)_50%,var(--color-background))]"
    >
      {Notice ? <Notice /> : null}
      <ComposerQueue />
      {allowAttachments ? <ComposerAttachments /> : null}
      <ComposerPrimitive.Input
        ref={inputRef}
        placeholder={placeholder}
        className="aui-composer-input caret-primary placeholder:text-muted-foreground/60 max-h-48 min-h-10 w-full resize-none bg-transparent px-2.5 py-1 text-base leading-6 outline-none"
        rows={1}
        autoFocus={autoFocus}
        enterKeyHint="send"
        aria-label="消息输入"
        onKeyDown={handlePlaceholderTab}
      />
      <ComposerAction />
    </div>
  );
  return (
    <ComposerPrimitive.Unstable_TriggerPopoverRoot>
      <ComposerPrimitive.Root
        className="aui-composer-root relative flex w-full flex-col"
        onSubmit={(e) => {
          // 运行中发送进入排队通道按序等待，不走 steer（steer 会打断当前一轮）。
          e.preventDefault();
          void aui.composer().send({ steer: false });
        }}
      >
        {allowAttachments ? (
          <ComposerPrimitive.AttachmentDropzone asChild>
            {shell}
          </ComposerPrimitive.AttachmentDropzone>
        ) : (
          shell
        )}
        <ComposerSlash />
        {mentions ? <ComposerMention source={mentions} /> : null}
      </ComposerPrimitive.Root>
    </ComposerPrimitive.Unstable_TriggerPopoverRoot>
  );
};

/** 排队消息区：仅在运行时支持排队且队列非空时占位。 */
const ComposerQueue: FC = () => {
  const count = useAuiState((s) => s.composer.queue.length);
  const { paused, resume } = useComposerQueueControl();
  if (count === 0) return null;
  return (
    <div data-slot="aui_composer-queue" className="flex flex-col gap-1 px-1">
      {paused ? (
        <div className="text-muted-foreground flex items-center justify-between gap-2 px-1.5 text-xs">
          <span>上一轮未正常结束，排队消息已暂停</span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-6 px-2 text-xs"
            onClick={resume}
          >
            继续发送
          </Button>
        </div>
      ) : null}
      <ComposerPrimitive.Queue>
        {({ queueItem }) => <ComposerQueueRow id={queueItem.id} />}
      </ComposerPrimitive.Queue>
    </div>
  );
};

const ComposerQueueRow: FC<{ id: string }> = ({ id }) => {
  const aui = useAui();
  const headId = useAuiState((s) => s.composer.queue[0]?.id ?? null);
  return (
    <div
      data-slot="aui_composer-queue-item"
      className="hover:bg-row-hover flex items-center gap-2 rounded-md px-1.5 py-1 text-sm"
    >
      <QueueItemPrimitive.Text className="text-muted-foreground min-w-0 flex-1 truncate" />
      {headId && headId !== id ? (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-6 px-2 text-xs"
          onClick={() => aui.queueItem.move({ lane: "queue", insertBefore: headId })}
        >
          插队到下一轮
        </Button>
      ) : null}
      <QueueItemPrimitive.Remove asChild>
        <Button type="button" variant="ghost" size="sm" className="h-6 px-2 text-xs">
          撤回
        </Button>
      </QueueItemPrimitive.Remove>
    </div>
  );
};

const ACTION_ICON_CLASS =
  "text-muted-foreground hover:text-foreground size-7 rounded-full";

const QuickCommandsButton: FC = () => {
  const { builtins, skills, context } = useComposerCommands();
  const aui = useAui();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <TooltipIconButton
          tooltip="快捷指令"
          side="bottom"
          type="button"
          variant="ghost"
          size="icon"
          className={ACTION_ICON_CLASS}
          aria-label="快捷指令"
        >
          <SlashIcon className="size-4" />
        </TooltipIconButton>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="start" collisionPadding={8} className="w-64">
        <QuickCommandItems
          builtins={builtins}
          skills={skills}
          onRun={(cmd) => cmd.execute(context)}
          onSkill={(skill) => appendSkillDirective(aui, skill)}
        />
      </DropdownMenuContent>
    </DropdownMenu>
  );
};

const QuickCommandItems: FC<{
  builtins: readonly SlashCommandDef[];
  skills?: readonly SkillCommand[];
  onRun: (cmd: SlashCommandDef) => void;
  onSkill?: (skill: SkillCommand) => void;
}> = ({ builtins, skills = [], onRun, onSkill }) => (
  <>
    <DropdownMenuLabel className="text-muted-foreground text-xs font-normal">
      命令
    </DropdownMenuLabel>
    {builtins.map((cmd) => {
      const Icon = resolveSlashIcon(cmd.icon);
      return (
        <DropdownMenuItem
          key={cmd.id}
          onSelect={() => onRun(cmd)}
          className="flex flex-col items-start gap-0.5"
        >
          <span className="flex items-center gap-2">
            <Icon className="text-muted-foreground size-4 shrink-0" aria-hidden />
            <span>{cmd.label}</span>
          </span>
          {cmd.description ? (
            <span className="text-muted-foreground pl-6 text-xs">{cmd.description}</span>
          ) : null}
        </DropdownMenuItem>
      );
    })}
    {skills.length > 0 && onSkill ? (
      <>
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="text-muted-foreground text-xs font-normal">
          技能
        </DropdownMenuLabel>
        {skills.map((skill) => {
          const Icon = resolveSlashIcon("skill");
          return (
            <DropdownMenuItem
              key={skill.id}
              onSelect={() => onSkill(skill)}
              className="flex flex-col items-start gap-0.5"
            >
              <span className="flex items-center gap-2">
                <Icon className="text-muted-foreground size-4 shrink-0" aria-hidden />
                <span>{skill.name}</span>
              </span>
              {skill.description ? (
                <span className="text-muted-foreground line-clamp-2 pl-6 text-xs">
                  {skill.description}
                </span>
              ) : null}
            </DropdownMenuItem>
          );
        })}
      </>
    ) : null}
  </>
);

const NewThreadButton: FC<{ onNew: () => void }> = ({ onNew }) => (
  <TooltipIconButton
    tooltip="新会话"
    side="bottom"
    type="button"
    variant="ghost"
    size="icon"
    className={ACTION_ICON_CLASS}
    aria-label="新会话"
    onClick={onNew}
  >
    <SquarePenIcon className="size-4" />
  </TooltipIconButton>
);

/** 窄屏（容器 < 28rem）时收起操作行左侧的附件、快捷指令与新会话。 */
const ComposerOverflowMenu: FC<{ onNew: (() => void) | null }> = ({ onNew }) => {
  const allowAttachments = useContext(AllowAttachmentsContext);
  const { builtins, skills, context } = useComposerCommands();
  const aui = useAui();
  const fileRef = useRef<HTMLInputElement>(null);
  return (
    <div className="hidden @max-[28rem]:flex" data-slot="aui_composer-overflow">
      {allowAttachments ? (
        <input
          ref={fileRef}
          type="file"
          multiple
          hidden
          onChange={(e) => {
            for (const file of Array.from(e.target.files ?? [])) {
              void aui.composer().addAttachment(file);
            }
            e.target.value = "";
          }}
        />
      ) : null}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <TooltipIconButton
            tooltip="更多操作"
            side="bottom"
            type="button"
            variant="ghost"
            size="icon"
            className={ACTION_ICON_CLASS}
            aria-label="更多操作"
          >
            <PlusIcon className="size-4" />
          </TooltipIconButton>
        </DropdownMenuTrigger>
        <DropdownMenuContent side="top" align="start" collisionPadding={8} className="w-56">
          {allowAttachments ? (
            <DropdownMenuItem onSelect={() => fileRef.current?.click()}>
              <PaperclipIcon className="size-4" />
              添加附件
            </DropdownMenuItem>
          ) : null}
          {onNew ? (
            <DropdownMenuItem onSelect={onNew}>
              <SquarePenIcon className="size-4" />
              新会话
            </DropdownMenuItem>
          ) : null}
          <DropdownMenuSeparator />
          <QuickCommandItems
            builtins={builtins}
            skills={skills}
            onRun={(cmd) => cmd.execute(context)}
            onSkill={(skill) => appendSkillDirective(aui, skill)}
          />
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
};

/** 运行中的发送：提交表单，进入排队通道。 */
const QueueSendButton: FC = () => {
  const empty = useAuiState((s) => s.composer.isEmpty);
  return (
    <TooltipIconButton
      tooltip="发送"
      side="bottom"
      type="submit"
      variant="default"
      size="icon"
      disabled={empty}
      className="aui-composer-send size-7 rounded-full"
      aria-label="发送"
    >
      <ArrowUpIcon className="size-4" />
    </TooltipIconButton>
  );
};

const ComposerAction: FC = () => {
  const allowAttachments = useContext(AllowAttachmentsContext);
  const { Start, End } = useThreadComposerOptions();
  const onNew = useNewThreadAction();
  const { markStopped } = useComposerQueueControl();
  return (
    <div
      data-slot="aui_composer-actions"
      className="aui-composer-action-wrapper relative flex items-center justify-between gap-2"
    >
      <div className="flex min-w-0 items-center gap-1">
        {Start ? <Start /> : null}
        <div
          data-slot="aui_composer-start-tools"
          className="flex items-center gap-1 @max-[28rem]:hidden"
        >
          {allowAttachments ? <ComposerAttachmentMenu /> : null}
          <QuickCommandsButton />
          {onNew ? <NewThreadButton onNew={onNew} /> : null}
        </div>
        <ComposerOverflowMenu onNew={onNew} />
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        {End ? <End /> : null}
        <AuiIf condition={(s) => s.thread.capabilities.dictation}>
          <AuiIf condition={(s) => s.composer.dictation == null}>
            <ComposerPrimitive.Dictate asChild>
              <TooltipIconButton
                tooltip="语音输入"
                side="bottom"
                type="button"
                variant="ghost"
                size="icon"
                className={cn("aui-composer-dictate", ACTION_ICON_CLASS)}
                aria-label="语音输入"
              >
                <MicIcon className="aui-composer-dictate-icon size-4" />
              </TooltipIconButton>
            </ComposerPrimitive.Dictate>
          </AuiIf>
          <AuiIf condition={(s) => s.composer.dictation != null}>
            <ComposerPrimitive.StopDictation asChild>
              <TooltipIconButton
                tooltip="停止语音输入"
                side="bottom"
                type="button"
                variant="ghost"
                size="icon"
                className="aui-composer-stop-dictation text-destructive size-7 rounded-full"
                aria-label="停止语音输入"
              >
                <SquareIcon className="aui-composer-stop-dictation-icon size-3.5 animate-pulse fill-current" />
              </TooltipIconButton>
            </ComposerPrimitive.StopDictation>
          </AuiIf>
        </AuiIf>
        <AuiIf
          condition={(s) =>
            s.thread.isRunning && !s.thread.capabilities.queue && !s.composer.isEmpty
          }
        >
          <span className="text-muted-foreground text-xs">需等待本轮结束</span>
        </AuiIf>
        <AuiIf
          condition={(s) =>
            s.thread.isRunning &&
            s.thread.capabilities.queue &&
            s.composer.queue.length < MAX_QUEUE
          }
        >
          <QueueSendButton />
        </AuiIf>
        <AuiIf condition={(s) => !s.thread.isRunning}>
          <ComposerPrimitive.Send asChild>
            <TooltipIconButton
              tooltip="发送"
              side="bottom"
              type="button"
              variant="default"
              size="icon"
              className="aui-composer-send size-7 rounded-full"
              aria-label="发送"
            >
              <ArrowUpIcon className="aui-composer-send-icon size-4" />
            </TooltipIconButton>
          </ComposerPrimitive.Send>
        </AuiIf>
        <AuiIf
          condition={(s) =>
            s.thread.isRunning &&
            s.thread.capabilities.queue &&
            s.composer.queue.length >= MAX_QUEUE
          }
        >
          <TooltipIconButton
            tooltip="最多排队 5 条"
            side="bottom"
            type="button"
            variant="default"
            size="icon"
            disabled
            className="aui-composer-send size-7 rounded-full"
            aria-label="发送"
          >
            <ArrowUpIcon className="size-4" />
          </TooltipIconButton>
        </AuiIf>
        <AuiIf condition={(s) => s.thread.isRunning}>
          <ComposerPrimitive.Cancel asChild>
            <Button
              type="button"
              variant="default"
              size="icon"
              className="aui-composer-cancel size-7 rounded-full"
              aria-label="停止"
              onClick={markStopped}
            >
              <SquareIcon className="aui-composer-cancel-icon size-3.5 fill-current" />
            </Button>
          </ComposerPrimitive.Cancel>
        </AuiIf>
      </div>
    </div>
  );
};

const MessageError: FC = () => {
  return (
    <MessagePrimitive.Error>
      <ErrorPrimitive.Root className="aui-message-error-root border-destructive bg-destructive/10 text-destructive mt-2 rounded-md border p-3 text-sm">
        <ErrorPrimitive.Message className="aui-message-error-message line-clamp-2" />
      </ErrorPrimitive.Root>
    </MessagePrimitive.Error>
  );
};

/**
 * 摘要条独立成组件：每秒 tick 只重渲这一行，不带动整条消息内容。
 * 耗时按整轮口径（见 `useTurnProcessDuration`），单条消息的 timing 只作回退。
 */
const ProcessSummaryLine: FC<{
  parts: readonly LoosePart[];
  running: boolean;
  expanded: boolean;
  onToggle: () => void;
}> = ({ parts, running, expanded, onToggle }) => {
  const timing = useMessageTiming();
  const durationMs = useTurnProcessDuration(timing?.totalStreamTime);
  const line = summaryLine(parts, durationMs, running);
  if (!line) return null;

  return (
    <button
      type="button"
      data-slot="process-summary"
      aria-expanded={expanded}
      className="text-muted-foreground mb-2 text-left text-sm"
      onClick={onToggle}
    >
      {running ? <InlineLoader label={line} /> : line}
    </button>
  );
};

const INLINE_LOADER_CLASS =
  "inline-flex flex-row gap-2 [&_[aria-hidden]]:gap-0.5 [&_[aria-hidden]_span]:size-1";

/** 官方 GenerationLoader 的行内横排版；tick 留在本组件内，只重渲这一行。 */
const InlineLoader: FC<{ label: string; className?: string }> = ({
  label,
  className,
}) => {
  const reduced = useReducedMotionConfig();
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (reduced) return;
    const id = setInterval(() => setTick((t) => t + 1), 120);
    return () => clearInterval(id);
  }, [reduced]);
  return (
    <GenerationLoader
      label={label}
      tick={tick}
      className={cn(INLINE_LOADER_CLASS, className)}
    />
  );
};

const WorkingIndicator: FC = () => (
  <span
    data-slot="aui_assistant-message-indicator"
    className="inline-flex"
    aria-label={PROCESS_COPY.running}
  >
    <InlineLoader label={PROCESS_COPY.running} />
  </span>
);

const AssistantMessage: FC = () => {
  const {
    ToolFallback: ToolFallbackComponent = SemanticToolFallback,
    ToolGroup,
    ReasoningGroup,
    TaskGroup: TaskGroupComponent,
  } = useContext(ThreadComponentsContext);
  const detail = useContext(ProcessDetailContext);
  const [expanded, setExpanded] = useState(false);
  const parts = useAuiState((s) => s.message.parts as LoosePart[]);
  const running = useAuiState((s) => s.message.status?.type === "running");
  const failed = useAuiState((s) => s.message.status?.type === "incomplete");
  const promptReady = promptUserCanSubmit({
    parts,
    messageRunning: running,
  });
  // 每次 promptUser 各自一层：作答后模型可能在同一条消息里紧接着再问，状态不能按整条消息算。
  const promptSurface = (part: PromptUserMessagePart, ui: ReactNode) => {
    // 服务端拒绝的组件树没有中断、也没被作答：不套「已回答」外框，交给工具 UI 自行降级。
    if (generativeRejection(part.result)) return ui;
    const pending = isPendingPromptUser(part);
    return (
      <GenerativeSurface
        kind="prompt"
        busy={pending && !promptReady}
        pending={pending}
        outcome={promptUserOutcome([part])}
        submitInput={promptUserSubmitInput([part])}
        inlineReceipt={isBoundaryAskPrompt(part)}
      >
        {ui}
      </GenerativeSurface>
    );
  };
  const showTraceBody = detail === "trace" || (detail === "summary" && expanded);
  const placeholder =
    detail === "minimal" ? minimalPlaceholder(parts, running, failed) : null;
  // 摘要档还没有任何步骤 / 推理（首个 token 之前）时，摘要条为空，靠指示点表明在工作。
  const summaryEmpty =
    detail === "summary" && summaryLine(parts, 0, running) === null;
  const groupBy = (
    part: Parameters<typeof messageGroupBy>[0],
    context?: Parameters<typeof messageGroupBy>[1],
  ): readonly ThreadGroupKey[] => {
    // present 单独成组，随 args 流式出现；promptUser 不成组，逐个渲染。
    if (isPresentTool(part)) return ["group-generative"];
    if (isPromptUserTool(part)) return [];
    // 面向用户的展示 / 提问卡属于结果时间线，任何档位都不收进工具组。注册表的 standalone
    // 标记在对话面未挂宿主 toolkit、或 toolkit 晚于首帧注册时缺失，不能作为唯一依据。
    if (part.type === "tool-call" && isUserFacingTool(part.toolName)) return [];
    return TaskGroupComponent
      ? taskAwareGroupBy(part, context)
      : messageGroupBy(part, context);
  };

  const ACTION_BAR_PT = "pt-1.5";
  // Keep the action bar inside the contained root's paint box, then cancel its reserved space in flow.
  const ACTION_BAR_HEIGHT = `min-h-7.5 ${ACTION_BAR_PT}`;

  return (
    <MessagePrimitive.Root
      data-slot="aui_assistant-message-root"
      data-role="assistant"
      className="relative -mb-7.5 pb-7.5 [contain-intrinsic-size:auto_200px] [content-visibility:auto]"
    >
      <div
        data-slot="aui_assistant-message-content"
        className="text-foreground px-2 leading-relaxed wrap-break-word"
      >
        {detail === "summary" ? (
          <ProcessSummaryLine
            parts={parts}
            running={running}
            expanded={expanded}
            onToggle={() => setExpanded((open) => !open)}
          />
        ) : null}
        {placeholder ? (
          <p data-slot="process-status" className="text-muted-foreground text-sm">
            {placeholder}
          </p>
        ) : null}
        <MessagePrimitive.GroupedParts groupBy={groupBy}>
          {({ part, children }) => {
            if (!showTraceBody) {
              switch (part.type) {
                case "group-chainOfThought":
                case "group-tool":
                case "group-task":
                  return children;
                case "group-generative":
                  return (
                    <GenerativeSurface kind="present">{children}</GenerativeSurface>
                  );
                case "group-reasoning":
                case "reasoning":
                  return null;
                case "indicator":
                  return summaryEmpty ? <WorkingIndicator /> : null;
                case "text":
                  return <MarkdownText />;
                case "data":
                  return part.dataRendererUI;
                case "file":
                  return (
                    <div data-slot="aui_assistant-message-file" className="py-1">
                      <File {...part} />
                    </div>
                  );
                case "image":
                  return (
                    <div data-slot="aui_assistant-message-image" className="py-1">
                      <Image {...part} />
                    </div>
                  );
                case "tool-call": {
                  if (part.toolName === "promptUser") {
                    return promptSurface(part, part.toolUI ?? null);
                  }
                  if (part.toolUI) return part.toolUI;
                  const kind = classifyPart(part);
                  if (kind === "timeline" || kind === "approval") {
                    return <ToolFallbackComponent {...part} />;
                  }
                  if (detail === "minimal" && kind === "brief") {
                    return (
                      <p data-slot="process-brief" className="text-sm">
                        {briefLine(part)}
                      </p>
                    );
                  }
                  if (detail === "minimal" && kind === "decided") {
                    return (
                      <p data-slot="process-decision" className="text-sm">
                        {decisionWord(part)} · {part.toolName}
                      </p>
                    );
                  }
                  // 写文件时模型要生成整份内容：过程中露出卡片，写完收回摘要条。
                  if (isLiveFileWrite(part)) {
                    return <ToolFallbackComponent {...part} />;
                  }
                  return null;
                }
                default:
                  return null;
              }
            }
            switch (part.type) {
              case "group-chainOfThought":
                return <div data-slot="aui_chain-of-thought">{children}</div>;
              case "group-task":
                return TaskGroupComponent ? (
                  <TaskGroupComponent group={part} />
                ) : null;
              case "group-tool":
                if (ToolGroup) {
                  return <ToolGroup group={part}>{children}</ToolGroup>;
                }
                return (
                  <ToolGroupRoot variant="ghost">
                    <ToolGroupTrigger
                      count={part.indices.length}
                      active={part.status.type === "running"}
                    />
                    <ToolGroupContent>{children}</ToolGroupContent>
                  </ToolGroupRoot>
                );
              case "group-generative":
                return (
                  <GenerativeSurface kind="present">{children}</GenerativeSurface>
                );
              case "group-reasoning": {
                if (ReasoningGroup) {
                  return (
                    <ReasoningGroup group={part}>{children}</ReasoningGroup>
                  );
                }
                const streaming = part.status.type === "running";
                return (
                  <ReasoningRoot streaming={streaming}>
                    <ReasoningTrigger active={streaming} />
                    <ReasoningContent aria-busy={streaming}>
                      <ReasoningText>{children}</ReasoningText>
                    </ReasoningContent>
                  </ReasoningRoot>
                );
              }
              case "text":
                return <MarkdownText />;
              case "reasoning":
                return <Reasoning {...part} />;
              case "tool-call":
                if (part.toolName === "promptUser") {
                  return promptSurface(
                    part,
                    part.toolUI ?? <ToolFallbackComponent {...part} />,
                  );
                }
                return part.toolUI ?? <ToolFallbackComponent {...part} />;
              case "data":
                return part.dataRendererUI;
              case "file":
                return (
                  <div data-slot="aui_assistant-message-file" className="py-1">
                    <File {...part} />
                  </div>
                );
              case "image":
                return (
                  <div data-slot="aui_assistant-message-image" className="py-1">
                    <Image {...part} />
                  </div>
                );
              case "indicator":
                return <WorkingIndicator />;
              default:
                return null;
            }
          }}
        </MessagePrimitive.GroupedParts>
        <MessageError />
        {/* 个人助手：本轮文件改动汇总（查看 / 撤销）；其余对话面与旧轮次仍是
            029 的本轮兜底产物卡片（模型只回路径时也能看到交付物）。 */}
        <TurnFileChanges fallback={<TurnArtifacts />} />
        {/* 047：个人助手 / 专家会话的建议卡与「已按你的习惯」标记；其余对话面无上下文，不渲染。 */}
        <GrowthTurnFooter />
      </div>

      <div
        data-slot="aui_assistant-message-footer"
        className={cn("ms-2 flex items-center", ACTION_BAR_HEIGHT)}
      >
        <BranchPicker />
        <AssistantActionBar />
      </div>
    </MessagePrimitive.Root>
  );
};

const COPIED_FEEDBACK_MS = 3000;

/**
 * 整条消息的可复制 Markdown：官方 `getCopyText` 只取文本块，结论放在
 * present / 结果卡 / 产物卡里时会复制不到（纯卡片回复连按钮都是灰的）。
 */
const useMessageMarkdown = (): string =>
  useAuiState((s) =>
    s.message.status?.type === "running"
      ? ""
      : messagePartsToMarkdown(s.message.parts),
  );

const MessageCopyButton: FC = () => {
  const aui = useAui();
  const markdown = useMessageMarkdown();
  const timer = useRef(0);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const copy = () => {
    if (!markdown) return;
    const message = aui.message;
    void copyText(markdown).then((ok) => {
      if (!ok) {
        toast.error("复制失败，请手动选中内容复制");
        return;
      }
      message.setIsCopied(true);
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(
        () => message.setIsCopied(false),
        COPIED_FEEDBACK_MS,
      );
    });
  };
  const isCopied = useAuiState((s) => s.message.isCopied);
  return (
    <TooltipIconButton
      tooltip={isCopied ? "已复制" : "复制"}
      disabled={!markdown}
      onClick={copy}
      data-copied={isCopied || undefined}
      className={cn(
        actionIconButton,
        "grid place-items-center data-[copied=true]:text-success",
      )}
    >
      <CheckIcon
        aria-hidden
        className={cn(iconSwap, isCopied ? iconSwapIn : iconSwapOut)}
      />
      <CopyIcon
        aria-hidden
        className={cn(iconSwap, isCopied ? iconSwapOut : iconSwapIn)}
      />
    </TooltipIconButton>
  );
};

const feedbackButton = cn(
  actionIconButton,
  "data-[submitted=true]:bg-foreground/[0.06] data-[submitted=true]:text-foreground/90 dark:data-[submitted=true]:bg-foreground/[0.09]",
);

const FeedbackButtons: FC = () => {
  const aui = useAui();
  const messageId = useAuiState((s) => s.message.id);
  const requestNegative = useContext(NegativeFeedbackRequest);
  const confirmNegative = (event: MouseEvent) => {
    if (!requestNegative) return;
    event.preventDefault();
    const message = aui.message;
    void requestNegative(messageId).then((confirmed) => {
      if (confirmed) message.submitFeedback({ type: "negative" });
    });
  };
  return (
    <>
      <ActionBarPrimitive.FeedbackPositive asChild>
        <TooltipIconButton tooltip="回答有帮助" className={feedbackButton}>
          <ThumbsUpIcon />
        </TooltipIconButton>
      </ActionBarPrimitive.FeedbackPositive>
      <ActionBarPrimitive.FeedbackNegative asChild onClick={confirmNegative}>
        <TooltipIconButton tooltip="回答没帮助" className={feedbackButton}>
          <ThumbsDownIcon />
        </TooltipIconButton>
      </ActionBarPrimitive.FeedbackNegative>
    </>
  );
};

const downloadMarkdown = (content: string) => {
  const blob = new Blob([content], { type: "text/markdown" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `message-${Date.now()}.md`;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 40_000);
};

const AssistantActionBar: FC = () => {
  const markdown = useMessageMarkdown();
  const extraActions = useContext(AssistantMessageActionsSlot);
  return (
    <ActionBarPrimitive.Root
      hideWhenRunning
      autohide="not-last"
      className="aui-assistant-action-bar-root text-muted-foreground col-start-3 row-start-2 -ms-1 flex gap-1"
    >
      <MessageCopyButton />
      <AuiIf condition={(s) => s.thread.capabilities.feedback}>
        <FeedbackButtons />
      </AuiIf>
      <AuiIf condition={(s) => s.thread.capabilities.reload}>
        <ActionBarPrimitive.Reload asChild>
          <TooltipIconButton tooltip="重新生成" className={actionIconButton}>
            <RefreshCwIcon />
          </TooltipIconButton>
        </ActionBarPrimitive.Reload>
      </AuiIf>
      <MessageTiming side="top" className="font-sans" />
      {extraActions}
      <ActionBarMorePrimitive.Root>
        <ActionBarMorePrimitive.Trigger asChild>
          <TooltipIconButton
            tooltip="更多"
            className={cn(
              actionIconButton,
              "data-[state=open]:bg-foreground/[0.06] data-[state=open]:text-foreground",
            )}
          >
            <MoreHorizontalIcon />
          </TooltipIconButton>
        </ActionBarMorePrimitive.Trigger>
        <ActionBarMorePrimitive.Content
          side="bottom"
          align="start"
          sideOffset={6}
          className={cn(
            floating,
            "aui-action-bar-more-content data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95 data-[state=open]:animate-in data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 data-[state=closed]:animate-out data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 z-50 min-w-[8rem] overflow-hidden p-1.5",
          )}
        >
          <ActionBarMorePrimitive.Item
            disabled={!markdown}
            onClick={() => downloadMarkdown(markdown)}
            className="aui-action-bar-more-item hover:bg-accent hover:text-accent-foreground focus:bg-accent focus:text-accent-foreground flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm outline-none select-none data-[disabled]:pointer-events-none data-[disabled]:opacity-50"
          >
            <DownloadIcon className="size-4" />
            导出为 Markdown
          </ActionBarMorePrimitive.Item>
        </ActionBarMorePrimitive.Content>
      </ActionBarMorePrimitive.Root>
    </ActionBarPrimitive.Root>
  );
};

const UserFilePart: FileMessagePartComponent = (part) => (
  <div data-slot="aui_user-message-file" className="py-1">
    <File {...part} />
  </div>
);

const UserImagePart: ImageMessagePartComponent = (part) => (
  <div data-slot="aui_user-message-image" className="py-1">
    <Image {...part} />
  </div>
);

/** 用户消息中的 `:skill[...]` / `:file[...]` 渲染为标记（024）。 */
const UserDirectiveText = createDirectiveText(defaultDirectiveFormatter, {
  iconMap: { skill: WandSparklesIcon },
  // 文件芯片与文件工作区同款类型图标（docx / xlsx / pdf 各有专属图形）。
  // 包一层 span 是因为 Badge 有 `[&>svg]:size-3`，直挂 svg 会被压到 12px。
  renderIcon: (seg) =>
    seg.type === "file" ? (
      <span
        data-slot="aui-directive-chip-icon"
        className="flex shrink-0 items-center self-center"
      >
        <AppFileIcon filename={seg.label} size={14} />
      </span>
    ) : null,
});

const UserMessage: FC = () => {
  return (
    <MessagePrimitive.Root
      data-slot="aui_user-message-root"
      className="grid auto-rows-auto grid-cols-[minmax(72px,1fr)_auto] content-start gap-y-2 px-2 [contain-intrinsic-size:auto_200px] [content-visibility:auto] [&:where(>*)]:col-start-2"
      data-role="user"
    >
      <UserMessageAttachments />

      <div className="aui-user-message-content-wrapper relative col-start-2 min-w-0">
        <div className="aui-user-message-content peer bg-muted text-foreground rounded-xl px-4 py-2 wrap-break-word empty:hidden">
          <MessagePrimitive.Parts
            components={{
              Text: UserDirectiveText,
              File: UserFilePart,
              Image: UserImagePart,
            }}
          />
        </div>
        <div className="aui-user-action-bar-wrapper absolute start-0 top-1/2 -translate-x-full -translate-y-1/2 pe-2 peer-empty:hidden rtl:translate-x-full">
          <UserActionBar />
        </div>
      </div>

      <BranchPicker
        data-slot="aui_user-branch-picker"
        className="col-span-full col-start-1 row-start-3 -me-1 justify-end"
      />
    </MessagePrimitive.Root>
  );
};

const UserActionBar: FC = () => {
  return (
    <ActionBarPrimitive.Root
      hideWhenRunning
      autohide="not-last"
      className="aui-user-action-bar-root flex flex-col items-end"
    >
      <ActionBarPrimitive.Edit asChild>
        <TooltipIconButton tooltip="编辑" className="aui-user-action-edit">
          <PencilIcon />
        </TooltipIconButton>
      </ActionBarPrimitive.Edit>
    </ActionBarPrimitive.Root>
  );
};

const EditComposer: FC = () => {
  return (
    <MessagePrimitive.Root
      data-slot="aui_edit-composer-wrapper"
      className="flex flex-col px-2 [contain-intrinsic-size:auto_200px] [content-visibility:auto]"
    >
      <ComposerPrimitive.Root className="aui-edit-composer-root border-composer-border shadow-composer ms-auto flex w-full max-w-[85%] cursor-text flex-col rounded-(--composer-radius) border bg-(--composer-bg)">
        <ComposerPrimitive.Input
          className="aui-edit-composer-input text-foreground min-h-14 w-full resize-none bg-transparent px-4 pt-3 pb-1 text-base outline-none"
          autoFocus
        />
        <div className="aui-edit-composer-footer mx-2.5 mb-2.5 flex items-center gap-1.5 self-end">
          <ComposerPrimitive.Cancel asChild>
            <Button
              variant="ghost"
              size="sm"
              className="h-8 rounded-full px-3.5"
            >
              取消
            </Button>
          </ComposerPrimitive.Cancel>
          <ComposerPrimitive.Send asChild>
            <Button size="sm" className="h-8 rounded-full px-3.5">
              更新
            </Button>
          </ComposerPrimitive.Send>
        </div>
      </ComposerPrimitive.Root>
    </MessagePrimitive.Root>
  );
};

const BranchPicker: FC<BranchPickerPrimitive.Root.Props> = ({
  className,
  ...rest
}) => {
  return (
    <BranchPickerPrimitive.Root
      hideWhenSingleBranch
      className={cn(
        "aui-branch-picker-root text-muted-foreground -ms-2 me-2 inline-flex items-center text-xs",
        className,
      )}
      {...rest}
    >
      <BranchPickerPrimitive.Previous asChild>
        <TooltipIconButton tooltip="上一个">
          <ChevronLeftIcon />
        </TooltipIconButton>
      </BranchPickerPrimitive.Previous>
      <span className="aui-branch-picker-state font-medium">
        <BranchPickerPrimitive.Number /> / <BranchPickerPrimitive.Count />
      </span>
      <BranchPickerPrimitive.Next asChild>
        <TooltipIconButton tooltip="下一个">
          <ChevronRightIcon />
        </TooltipIconButton>
      </BranchPickerPrimitive.Next>
    </BranchPickerPrimitive.Root>
  );
};
