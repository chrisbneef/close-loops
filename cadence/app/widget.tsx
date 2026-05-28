/**
 * Widget surface — /widget route. Compact dev-tool / game-HUD style overlay.
 * Distinct from the mobile Now screen (which stays minimalist + warm) so each
 * surface matches its use: focused execution on mobile, quick-glance multi-task
 * review on desktop.
 *
 * Layout (matches the TaskFlow reference but rebranded):
 *   ┌─────────────────────────────────────┐
 *   │ ▲ CLOSE YOUR LOOPS NOOB     Tue 5/19│
 *   ├─────────────────────────────────────┤
 *   │ ▾ Deploy staging         15m  Start │
 *   │   ░ importance 9/10                  │
 *   │   ☐ Pull main into staging branch    │
 *   │   ☑ Run smoke tests locally          │
 *   │   ☐ Push to staging.preapprove.me    │
 *   ├─────────────────────────────────────┤
 *   │ ▸ Reply to support emails  20m Start│
 *   ├─────────────────────────────────────┤
 *   │ ▸ Run prod smoke tests    25m  Start│
 *   └─────────────────────────────────────┘
 *
 * Owner switcher reused from the mobile screen pattern — same useState +
 * pills approach so user can demo as either cofounder.
 */

import { useEffect, useState } from 'react';
import {
  Pressable, ScrollView, StyleSheet, Text, TextInput, View,
} from 'react-native';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  api, type NextActionResponse, type SubtaskOut, type TaskOut,
} from '@/src/api';
import { useAuth } from '@/src/auth-store';
import { formatTimer, useTimer } from '@/src/timer-store';
import {
  WIDGET_MAX_WIDTH, widgetColors as c, widgetRadii as r,
  widgetSpacing as sp, widgetType as t,
} from '@/src/widget-theme';

const OWNERS = [
  { id: 1, name: 'Michael' },
  { id: 2, name: 'Chris' },
] as const;

export default function WidgetScreen() {
  const authUserId = useAuth((s) => s.user?.id ?? 1) as 1 | 2;
  const [ownerId, setOwnerId] = useState<1 | 2>(authUserId);
  const [expandedTaskId, setExpandedTaskId] = useState<number | null>(null);
  const [collapsed, setCollapsed] = useState(false);

  const nextActionQuery = useQuery({
    queryKey: ['next-action', ownerId],
    queryFn: () => api.getNextAction(ownerId),
    refetchInterval: 30_000,
  });

  // All visible tasks = current + up_next (max 3 from /next-action).
  const tasks: TaskOut[] = (() => {
    const data = nextActionQuery.data;
    if (!data?.current) return [];
    return [data.current, ...data.up_next];
  })();

  // Auto-expand the current (top) task on first load so the user sees subtasks
  // immediately — re-collapse only via explicit user action.
  useEffect(() => {
    if (tasks.length > 0 && expandedTaskId === null) {
      setExpandedTaskId(tasks[0].id);
    }
  }, [tasks.length === 0 ? 0 : tasks[0].id]);

  // Collapsed surface: just a single-line pill with the top task title.
  // Click it (or the chevron) to expand back. Click the brand area in the
  // expanded view to collapse. Keeps the widget out of the way during deep
  // work while leaving a single signal of what's next.
  if (collapsed) {
    const top = tasks[0];
    return (
      <View style={s.page}>
        <Pressable onPress={() => setCollapsed(false)} style={s.collapsed}>
          <View style={s.logoDot} />
          <Text style={s.collapsedTitle} numberOfLines={1}>
            {top ? top.title : 'CLOSE YOUR LOOPS NOOB'}
          </Text>
          <Text style={s.collapsedChevron}>▾</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <View style={s.page}>
      <View style={s.widget}>
        <Header
          ownerId={ownerId}
          onSwitch={setOwnerId}
          onCollapse={() => setCollapsed(true)}
        />

        {nextActionQuery.isLoading ? (
          <View style={s.empty}>
            <Text style={s.emptyText}>LOADING…</Text>
          </View>
        ) : nextActionQuery.isError ? (
          <View style={s.empty}>
            <Text style={s.emptyText}>CAN'T REACH THE BRAIN</Text>
            <Text style={s.emptySub}>{String(nextActionQuery.error)}</Text>
          </View>
        ) : tasks.length === 0 ? (
          <View style={s.empty}>
            <Text style={s.emptyText}>QUEUE EMPTY</Text>
            <Text style={s.emptySub}>
              Nothing scheduled for this user.{'\n'}
              POST /ingest a goal, or switch user.
            </Text>
          </View>
        ) : (
          <ScrollView style={s.list} contentContainerStyle={s.listContent}>
            {tasks.map((task, idx) => (
              <TaskRow
                key={task.id}
                task={task}
                ownerId={ownerId}
                isFirst={idx === 0}
                expanded={expandedTaskId === task.id}
                onToggleExpand={() =>
                  setExpandedTaskId(expandedTaskId === task.id ? null : task.id)
                }
              />
            ))}
          </ScrollView>
        )}

        <AddTaskBar ownerId={ownerId} />
        <Footer />
      </View>
    </View>
  );
}

// ---------- Add task ----------

function AddTaskBar({ ownerId }: { ownerId: 1 | 2 }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [mins, setMins] = useState('25');

  const createMutation = useMutation({
    mutationFn: () => api.createTask(ownerId, title.trim(), parseInt(mins, 10) || 25),
    onSuccess: () => {
      setTitle('');
      setMins('25');
      setOpen(false);
      queryClient.invalidateQueries({ queryKey: ['next-action', ownerId] });
    },
  });

  const submit = () => {
    if (!title.trim() || createMutation.isPending) return;
    createMutation.mutate();
  };

  if (!open) {
    return (
      <Pressable
        onPress={() => setOpen(true)}
        style={({ pressed }) => [s.addTaskButton, pressed && { opacity: 0.7 }]}
      >
        <Text style={s.addTaskButtonText}>+ TASK</Text>
      </Pressable>
    );
  }

  return (
    <View style={s.addTaskForm}>
      <TextInput
        value={title}
        onChangeText={setTitle}
        onSubmitEditing={submit}
        placeholder="what needs doing?"
        placeholderTextColor={c.textFaint}
        style={s.addTaskInput}
        autoFocus
        returnKeyType="done"
      />
      <TextInput
        value={mins}
        onChangeText={setMins}
        style={s.addTaskMins}
        keyboardType="number-pad"
        maxLength={3}
      />
      <Text style={s.addTaskMinsLabel}>min</Text>
      <Pressable
        onPress={submit}
        disabled={!title.trim() || createMutation.isPending}
        style={({ pressed }) => [
          s.btnSmall, s.btnStart,
          pressed && { opacity: 0.85 },
          (!title.trim() || createMutation.isPending) && { opacity: 0.4 },
        ]}
      >
        <Text style={[s.btnText, { color: c.textOnAccent }]}>ADD</Text>
      </Pressable>
      <Pressable
        onPress={() => { setOpen(false); setTitle(''); }}
        style={({ pressed }) => [s.btnSmall, s.btnSkip, pressed && { opacity: 0.7 }]}
      >
        <Text style={[s.btnText, { color: c.textDim }]}>✕</Text>
      </Pressable>
    </View>
  );
}

// ---------- Header ----------

function Header({
  ownerId, onSwitch, onCollapse,
}: {
  ownerId: 1 | 2;
  onSwitch: (id: 1 | 2) => void;
  onCollapse: () => void;
}) {
  const today = new Date().toLocaleDateString('en-US', {
    weekday: 'short', month: 'short', day: 'numeric',
  });
  return (
    <View style={s.header}>
      <Pressable style={s.headerLeft} onPress={onCollapse}>
        <View style={s.logoDot} />
        <Text style={s.brand}>CLOSE YOUR LOOPS NOOB</Text>
        <Text style={s.collapseChevron}>▴</Text>
      </Pressable>
      <View style={s.headerRight}>
        <Text style={s.date}>{today.toUpperCase()}</Text>
      </View>
      <View style={s.ownerRow}>
        <Text style={s.ownerLabel}>USER</Text>
        {OWNERS.map((o) => (
          <Pressable
            key={o.id}
            onPress={() => onSwitch(o.id)}
            style={({ pressed }) => [
              s.ownerPill,
              ownerId === o.id && s.ownerPillActive,
              pressed && { opacity: 0.7 },
            ]}
          >
            <Text style={[s.ownerPillText, ownerId === o.id && s.ownerPillTextActive]}>
              {o.name}
            </Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}

// ---------- Task Row ----------

function TaskRow({
  task, ownerId, isFirst, expanded, onToggleExpand,
}: {
  task: TaskOut;
  ownerId: 1 | 2;
  isFirst: boolean;
  expanded: boolean;
  onToggleExpand: () => void;
}) {
  const queryClient = useQueryClient();
  const timer = useTimer();
  const [askingForReason, setAskingForReason] = useState(false);
  const [pauseReason, setPauseReason] = useState('');

  const startMutation = useMutation({
    mutationFn: () => api.startTask(task.id),
    onSuccess: () => {
      timer.start(task.id);
      queryClient.invalidateQueries({ queryKey: ['next-action', ownerId] });
    },
  });

  const pauseMutation = useMutation({
    mutationFn: (reason: string) => api.pauseTask(task.id, reason),
    onSuccess: () => {
      timer.pause();
      setAskingForReason(false);
      setPauseReason('');
      queryClient.invalidateQueries({ queryKey: ['next-action', ownerId] });
    },
  });

  const resumeMutation = useMutation({
    mutationFn: () => api.resumeTask(task.id),
    onSuccess: () => {
      timer.resume();
      queryClient.invalidateQueries({ queryKey: ['next-action', ownerId] });
    },
  });

  const doneMutation = useMutation({
    mutationFn: () => api.completeTask(task.id),
    onSuccess: (next) => {
      timer.reset();
      queryClient.setQueryData<NextActionResponse>(['next-action', ownerId], next);
    },
  });

  const isInProgress = task.status === 'in_progress';
  const isPaused = task.status === 'paused';
  const subtaskCount = task.subtasks.length;
  const subtaskDone = task.subtasks.filter((s) => s.completed).length;

  const submitPause = () => {
    const reason = pauseReason.trim();
    if (!reason) return;
    pauseMutation.mutate(reason);
  };

  return (
    <View style={[s.row, isFirst && s.rowActive]}>
      <Pressable onPress={onToggleExpand} style={s.rowHeader}>
        <Text style={s.chevron}>{expanded ? '▾' : '▸'}</Text>
        <View style={s.rowHeaderText}>
          <Text style={s.taskTitle} numberOfLines={2}>{task.title}</Text>
          <View style={s.rowMetaLine}>
            {isPaused && <Text style={s.statusPaused}>PAUSED · </Text>}
            <Text style={s.metaItem}>importance {task.importance}/10</Text>
            {subtaskCount > 0 && (
              <>
                <Text style={s.metaDot}>·</Text>
                <Text style={s.metaItem}>
                  {subtaskDone}/{subtaskCount} steps
                </Text>
              </>
            )}
          </View>
        </View>
        <View style={s.rowHeaderRight}>
          <Text style={s.duration}>{formatDuration(task.est_minutes)}</Text>
        </View>
      </Pressable>

      {expanded && (
        <View style={s.rowExpanded}>
          {/* Subtask checklist */}
          {task.subtasks.length > 0 && (
            <View style={s.subtasks}>
              {task.subtasks.map((sub) => (
                <SubtaskRow key={sub.id} taskId={task.id} subtask={sub} ownerId={ownerId} />
              ))}
            </View>
          )}

          {/* Add-subtask inline form */}
          <AddSubtaskInline taskId={task.id} ownerId={ownerId} />

          {/* Pause reason prompt — replaces the action row temporarily */}
          {askingForReason ? (
            <View style={s.pausePrompt}>
              <Text style={s.pausePromptLabel}>why are you pausing?</Text>
              <View style={s.pausePromptRow}>
                <TextInput
                  value={pauseReason}
                  onChangeText={setPauseReason}
                  onSubmitEditing={submitPause}
                  placeholder="e.g. slack ping, kid, coffee…"
                  placeholderTextColor={c.textFaint}
                  style={s.pauseInput}
                  autoFocus
                  returnKeyType="done"
                />
                <Pressable
                  onPress={submitPause}
                  disabled={!pauseReason.trim() || pauseMutation.isPending}
                  style={({ pressed }) => [
                    s.btnSmall, s.btnStart,
                    pressed && { opacity: 0.85 },
                    (!pauseReason.trim() || pauseMutation.isPending) && { opacity: 0.4 },
                  ]}
                >
                  <Text style={[s.btnText, { color: c.textOnAccent }]}>OK</Text>
                </Pressable>
                <Pressable
                  onPress={() => { setAskingForReason(false); setPauseReason(''); }}
                  style={({ pressed }) => [
                    s.btnSmall, s.btnSkip,
                    pressed && { opacity: 0.85 },
                  ]}
                >
                  <Text style={[s.btnText, { color: c.textDim }]}>cancel</Text>
                </Pressable>
              </View>
            </View>
          ) : (
            <View style={s.actions}>
              {/* Primary action: depends on current task status */}
              {isInProgress ? (
                <Pressable
                  onPress={() => setAskingForReason(true)}
                  disabled={pauseMutation.isPending}
                  style={({ pressed }) => [
                    s.btn, s.btnPause,
                    pressed && { opacity: 0.85 },
                    pauseMutation.isPending && { opacity: 0.5 },
                  ]}
                >
                  <Text style={[s.btnText, { color: c.text }]}>❚❚ PAUSE</Text>
                </Pressable>
              ) : isPaused ? (
                <Pressable
                  onPress={() => resumeMutation.mutate()}
                  disabled={resumeMutation.isPending}
                  style={({ pressed }) => [
                    s.btn, s.btnStart,
                    pressed && { opacity: 0.85 },
                    resumeMutation.isPending && { opacity: 0.5 },
                  ]}
                >
                  <Text style={[s.btnText, { color: c.textOnAccent }]}>▶ RESUME</Text>
                </Pressable>
              ) : (
                <Pressable
                  onPress={() => startMutation.mutate()}
                  disabled={startMutation.isPending}
                  style={({ pressed }) => [
                    s.btn, s.btnStart,
                    pressed && { opacity: 0.85 },
                    startMutation.isPending && { opacity: 0.5 },
                  ]}
                >
                  <Text style={[s.btnText, { color: c.textOnAccent }]}>▶ START</Text>
                </Pressable>
              )}
              <View style={s.btnSpacer} />
              {/* Done is always available (any state can complete) */}
              <Pressable
                onPress={() => doneMutation.mutate()}
                disabled={doneMutation.isPending}
                style={({ pressed }) => [
                  s.btn, s.btnDone,
                  pressed && { opacity: 0.85 },
                  doneMutation.isPending && { opacity: 0.5 },
                ]}
              >
                <Text style={[s.btnText, { color: c.textOnAccent }]}>✓ DONE</Text>
              </Pressable>
            </View>
          )}
        </View>
      )}
    </View>
  );
}

// ---------- Subtask Row ----------

function SubtaskRow({
  taskId, subtask, ownerId,
}: {
  taskId: number;
  subtask: SubtaskOut;
  ownerId: 1 | 2;
}) {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: (completed: boolean) =>
      api.toggleSubtask(taskId, subtask.id, completed),
    onSuccess: () => {
      // Refetch /next-action so the subtask checklist + count update.
      queryClient.invalidateQueries({ queryKey: ['next-action', ownerId] });
    },
  });

  return (
    <Pressable
      onPress={() => mutation.mutate(!subtask.completed)}
      style={({ pressed }) => [
        s.subtaskRow,
        pressed && { opacity: 0.7 },
      ]}
    >
      <View style={[s.checkbox, subtask.completed && s.checkboxDone]}>
        {subtask.completed && <Text style={s.checkmark}>✓</Text>}
      </View>
      <Text
        style={[s.subtaskText, subtask.completed && s.subtaskTextDone]}
        numberOfLines={2}
      >
        {subtask.title}
      </Text>
    </Pressable>
  );
}

// ---------- Add Subtask Inline ----------

function AddSubtaskInline({
  taskId, ownerId,
}: { taskId: number; ownerId: 1 | 2 }) {
  const [draft, setDraft] = useState('');
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: (title: string) => api.createSubtask(taskId, title),
    onSuccess: () => {
      setDraft('');
      queryClient.invalidateQueries({ queryKey: ['next-action', ownerId] });
    },
  });

  const submit = () => {
    const title = draft.trim();
    if (!title) return;
    mutation.mutate(title);
  };

  return (
    <View style={s.addRow}>
      <Text style={s.addPlus}>+</Text>
      <TextInput
        value={draft}
        onChangeText={setDraft}
        onSubmitEditing={submit}
        placeholder="add a step…"
        placeholderTextColor={c.textFaint}
        style={s.addInput}
        returnKeyType="done"
      />
    </View>
  );
}

// ---------- Footer ----------

function Footer() {
  return (
    <View style={s.footer}>
      <Text style={s.footerText}>backend: localhost:8000  ·  brain alive</Text>
    </View>
  );
}

// ---------- helpers ----------

function formatDuration(minutes: number): string {
  if (minutes < 60) return `${minutes}m`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

// ---------- styles ----------

const s = StyleSheet.create({
  page: {
    flex: 1,
    backgroundColor: c.bg,
    alignItems: 'center',
    justifyContent: 'flex-start',
    paddingTop: sp.xl,
    paddingHorizontal: sp.md,
  },
  widget: {
    width: '100%',
    maxWidth: WIDGET_MAX_WIDTH,
    backgroundColor: c.surface,
    borderRadius: r.lg,
    borderWidth: 1,
    borderColor: c.border,
    overflow: 'hidden',
  },

  // Header
  header: {
    paddingHorizontal: sp.md,
    paddingTop: sp.md,
    paddingBottom: sp.sm,
    borderBottomWidth: 1,
    borderBottomColor: c.border,
    backgroundColor: c.surfaceElevated,
  },
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: sp.sm,
  },
  logoDot: {
    width: 10,
    height: 10,
    borderRadius: r.pill,
    backgroundColor: c.accent,
  },
  brand: {
    ...t.hud,
    color: c.text,
  },
  headerRight: {
    position: 'absolute',
    top: sp.md,
    right: sp.md,
  },
  date: {
    ...t.micro,
    color: c.textDim,
  },
  ownerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: sp.xs,
    marginTop: sp.sm,
  },
  ownerLabel: {
    ...t.micro,
    color: c.textFaint,
    marginRight: sp.xs,
  },
  ownerPill: {
    paddingHorizontal: sp.sm,
    paddingVertical: 3,
    borderRadius: r.sm,
    borderWidth: 1,
    borderColor: c.border,
  },
  ownerPillActive: {
    backgroundColor: c.accent,
    borderColor: c.accent,
  },
  ownerPillText: {
    ...t.micro,
    color: c.textDim,
  },
  ownerPillTextActive: {
    color: c.textOnAccent,
  },

  // Empty / loading
  empty: {
    paddingVertical: sp.xl * 2,
    alignItems: 'center',
    gap: sp.sm,
  },
  emptyText: {
    ...t.hud,
    color: c.textDim,
  },
  emptySub: {
    ...t.taskMeta,
    color: c.textFaint,
    textAlign: 'center',
  },

  // List + rows
  list: {
    maxHeight: 600,
  },
  listContent: {
    paddingBottom: sp.sm,
  },
  row: {
    borderBottomWidth: 1,
    borderBottomColor: c.border,
    paddingHorizontal: sp.md,
    paddingVertical: sp.md,
    borderLeftWidth: 3,
    borderLeftColor: 'transparent',
  },
  rowActive: {
    borderLeftColor: c.accent,
    backgroundColor: c.surfaceHover,
  },
  rowHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: sp.sm,
  },
  chevron: {
    color: c.textDim,
    fontSize: 12,
    lineHeight: 20,
    width: 12,
  },
  rowHeaderText: {
    flex: 1,
    minWidth: 0,
  },
  taskTitle: {
    ...t.taskTitle,
    color: c.text,
  },
  rowMetaLine: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: sp.xs,
    marginTop: 2,
  },
  metaItem: {
    ...t.taskMeta,
    color: c.textDim,
  },
  metaDot: {
    ...t.taskMeta,
    color: c.textFaint,
  },
  rowHeaderRight: {
    paddingTop: 3,
  },
  duration: {
    ...t.duration,
    color: c.textDim,
  },

  // Expanded body
  rowExpanded: {
    marginTop: sp.md,
    paddingLeft: sp.xl,
  },

  // Subtasks
  subtasks: {
    gap: sp.xs,
    marginBottom: sp.sm,
  },
  subtaskRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: sp.sm,
    paddingVertical: 3,
  },
  checkbox: {
    width: 16,
    height: 16,
    borderRadius: r.sm,
    borderWidth: 1.5,
    borderColor: c.border,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 1,
  },
  checkboxDone: {
    backgroundColor: c.done,
    borderColor: c.done,
  },
  checkmark: {
    color: c.textOnAccent,
    fontSize: 11,
    fontWeight: 'bold',
    lineHeight: 12,
  },
  subtaskText: {
    ...t.subtask,
    color: c.text,
    flex: 1,
  },
  subtaskTextDone: {
    color: c.textFaint,
    textDecorationLine: 'line-through',
  },

  // Add subtask inline
  addRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: sp.sm,
    paddingVertical: 3,
    marginBottom: sp.md,
  },
  addPlus: {
    color: c.textFaint,
    fontSize: 14,
    width: 16,
    textAlign: 'center',
  },
  addInput: {
    ...t.subtask,
    flex: 1,
    color: c.text,
    paddingVertical: 2,
    // ts: react-native style accepts outlineWidth on web
    outlineStyle: 'none' as any,
  },

  // Actions
  actions: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  btn: {
    paddingHorizontal: sp.md,
    paddingVertical: sp.sm,
    borderRadius: r.md,
    minWidth: 90,
    alignItems: 'center',
  },
  btnStart: {
    backgroundColor: c.accent,
  },
  btnDone: {
    backgroundColor: c.done,
  },
  btnPause: {
    backgroundColor: 'transparent',
    borderWidth: 1,
    borderColor: c.border,
  },
  btnSkip: {
    backgroundColor: 'transparent',
    borderWidth: 1,
    borderColor: c.border,
  },
  btnSmall: {
    paddingHorizontal: sp.sm,
    paddingVertical: 6,
    borderRadius: r.md,
    alignItems: 'center',
    justifyContent: 'center',
  },
  btnSpacer: {
    width: sp.sm,
  },
  btnText: {
    ...t.button,
  },

  // Pause prompt
  pausePrompt: {
    backgroundColor: c.surfaceHover,
    borderRadius: r.md,
    padding: sp.sm,
    marginTop: sp.xs,
  },
  pausePromptLabel: {
    ...t.micro,
    color: c.textDim,
    marginBottom: sp.xs,
  },
  pausePromptRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: sp.xs,
  },
  pauseInput: {
    ...t.subtask,
    flex: 1,
    color: c.text,
    backgroundColor: c.bg,
    borderRadius: r.sm,
    paddingHorizontal: sp.sm,
    paddingVertical: 6,
    borderWidth: 1,
    borderColor: c.border,
    outlineStyle: 'none' as any,
  },

  // Paused status badge (in the meta row of the task header)
  statusPaused: {
    ...t.micro,
    color: c.warning,
    letterSpacing: 1.0,
  },

  // Collapse chevron in the header (click brand to collapse)
  collapseChevron: {
    color: c.textFaint,
    fontSize: 10,
    marginLeft: sp.xs,
  },

  // Collapsed surface — single-line pill
  collapsed: {
    width: '100%',
    maxWidth: WIDGET_MAX_WIDTH,
    flexDirection: 'row',
    alignItems: 'center',
    gap: sp.sm,
    paddingVertical: sp.sm,
    paddingHorizontal: sp.md,
    backgroundColor: c.surface,
    borderRadius: r.pill,
    borderWidth: 1,
    borderColor: c.border,
  },
  collapsedTitle: {
    ...t.taskMeta,
    color: c.text,
    flex: 1,
  },
  collapsedChevron: {
    color: c.accent,
    fontSize: 14,
  },

  // Add-task bar
  addTaskButton: {
    marginTop: sp.sm,
    marginBottom: sp.xs,
    paddingVertical: sp.sm,
    borderRadius: r.md,
    borderWidth: 1,
    borderStyle: 'dashed',
    borderColor: c.border,
    alignItems: 'center',
  },
  addTaskButtonText: {
    ...t.duration,
    color: c.textDim,
  },
  addTaskForm: {
    marginTop: sp.sm,
    marginBottom: sp.xs,
    flexDirection: 'row',
    alignItems: 'center',
    gap: sp.xs,
  },
  addTaskInput: {
    ...t.taskMeta,
    flex: 1,
    color: c.text,
    backgroundColor: c.surfaceHover,
    borderRadius: r.sm,
    paddingHorizontal: sp.sm,
    paddingVertical: 7,
    borderWidth: 1,
    borderColor: c.border,
    outlineStyle: 'none' as any,
  },
  addTaskMins: {
    ...t.duration,
    width: 38,
    color: c.text,
    backgroundColor: c.surfaceHover,
    borderRadius: r.sm,
    paddingHorizontal: sp.xs,
    paddingVertical: 7,
    borderWidth: 1,
    borderColor: c.border,
    textAlign: 'center',
    outlineStyle: 'none' as any,
  },
  addTaskMinsLabel: {
    ...t.micro,
    color: c.textFaint,
    marginRight: sp.xs,
  },

  // Footer
  footer: {
    paddingHorizontal: sp.md,
    paddingVertical: sp.sm,
    borderTopWidth: 1,
    borderTopColor: c.border,
    backgroundColor: c.surfaceElevated,
  },
  footerText: {
    ...t.micro,
    color: c.textFaint,
    textAlign: 'center',
  },
});
