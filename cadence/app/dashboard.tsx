/**
 * Desktop dashboard — the third surface (alongside the mobile Now screen and
 * the compact widget). A Kanban board of every task by status, a list-view
 * toggle, an owner toggle (Michael ↔ Chris), and a right sidebar showing the
 * owner's scheduled "today" list (the same /next-action the widget renders).
 *
 * Click-to-move between columns (no drag-drop in v1) via the shared
 * useTaskMove hook. Widget-themed (dark slate + electric lime) so the
 * dashboard and widget feel like one desktop product.
 */

import { useState } from 'react';
import {
  Pressable, ScrollView, StyleSheet, Text, TextInput, useWindowDimensions, View,
} from 'react-native';
import { Link } from 'expo-router';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, type TaskOut } from '@/src/api';
import { useAuth } from '@/src/auth-store';
import { DateField } from '@/src/components/DateField';
import { OwnerSwitcher } from '@/src/components/OwnerSwitcher';
import { TaskCard } from '@/src/components/TaskCard';
import { COLUMNS, columnFor, type ColumnKey } from '@/src/components/move-task';
import {
  widgetColors as c, widgetRadii as r, widgetSpacing as sp, widgetType as t,
} from '@/src/widget-theme';

type ViewMode = 'kanban' | 'list';

export default function DashboardScreen() {
  const authUserId = useAuth((s) => s.user?.id ?? 1) as 1 | 2;
  const logout = useAuth((s) => s.logout);
  // Below this width the 5-up Kanban + side rail won't fit — collapse to a
  // single-column, tab-navigated phone layout.
  const { width } = useWindowDimensions();
  const narrow = width < 760;
  const [ownerId, setOwnerId] = useState<1 | 2>(authUserId);
  const [view, setView] = useState<ViewMode>('kanban');
  const [newTaskOpen, setNewTaskOpen] = useState(false);
  const [editingTask, setEditingTask] = useState<TaskOut | null>(null);

  const tasksQuery = useQuery({
    queryKey: ['tasks', ownerId],
    queryFn: () => api.listTasks(ownerId),
    refetchInterval: 30_000,
  });
  const nextQuery = useQuery({
    queryKey: ['next-action', ownerId],
    queryFn: () => api.getNextAction(ownerId),
    refetchInterval: 30_000,
  });

  const tasks = tasksQuery.data ?? [];

  return (
    <View style={s.root}>
      {/* Top bar */}
      <View style={[s.topbar, narrow && s.topbarNarrow]}>
        <View style={s.brandRow}>
          <View style={s.logoDot} />
          <Text style={s.brand} numberOfLines={1}>CLOSE YOUR LOOPS NOOB</Text>
          {!narrow && <Text style={s.brandSub}>· dashboard</Text>}
        </View>
        <View style={[s.topbarRight, narrow && s.topbarRightNarrow]}>
          <Pressable
            onPress={() => setNewTaskOpen((open) => !open)}
            style={({ pressed }) => [s.newTaskTrigger, pressed && { opacity: 0.85 }]}
          >
            <Text style={s.newTaskTriggerText}>+ NEW TASK</Text>
          </Pressable>
          <OwnerSwitcher active={ownerId} onChange={setOwnerId} />
          <View style={s.viewToggle}>
            <ViewTab label="KANBAN" on={view === 'kanban'} onPress={() => setView('kanban')} />
            <ViewTab label="LIST" on={view === 'list'} onPress={() => setView('list')} />
          </View>
          <Link href="/reports" style={s.navLink}>REPORTS</Link>
          <Pressable onPress={() => logout()} hitSlop={6}>
            <Text style={s.signOut}>SIGN OUT</Text>
          </Pressable>
        </View>
      </View>

      {/* Body: main area + right sidebar (the rail folds away on phones) */}
      <View style={[s.body, narrow && s.bodyNarrow]}>
        <View style={[s.main, narrow && s.mainNarrow]}>
          {tasksQuery.isLoading ? (
            <Text style={s.muted}>Loading…</Text>
          ) : tasksQuery.isError ? (
            <Text style={s.muted}>Can't reach the brain.</Text>
          ) : tasks.length === 0 ? (
            <EmptyBoard
              ownerId={ownerId}
              onAdd={() => setNewTaskOpen(true)}
            />
          ) : view === 'kanban' ? (
            <KanbanBoard tasks={tasks} ownerId={ownerId} onEdit={setEditingTask} narrow={narrow} />
          ) : (
            <ListView tasks={tasks} ownerId={ownerId} onEdit={setEditingTask} />
          )}
        </View>

        {!narrow && (
          <View style={s.sidebar}>
            <Text style={s.sidebarHeading}>TODAY</Text>
            {nextQuery.data?.current ? (
              <ScrollView showsVerticalScrollIndicator={false}>
                {[nextQuery.data.current, ...nextQuery.data.up_next].map((task) => (
                  <TaskCard
                    key={task.id}
                    task={task}
                    ownerId={ownerId}
                    onEdit={setEditingTask}
                  />
                ))}
              </ScrollView>
            ) : (
              <Text style={s.muted}>Nothing scheduled right now.</Text>
            )}
          </View>
        )}
      </View>

      {/* Task popover — handles both create and edit. */}
      {(newTaskOpen || editingTask) && (
        <TaskModal
          ownerId={ownerId}
          editingTask={editingTask ?? undefined}
          onClose={() => { setNewTaskOpen(false); setEditingTask(null); }}
        />
      )}
    </View>
  );
}

function KanbanBoard({
  tasks, ownerId, onEdit, narrow,
}: { tasks: TaskOut[]; ownerId: 1 | 2; onEdit: (task: TaskOut) => void; narrow: boolean }) {
  const buckets: Record<string, TaskOut[]> = Object.fromEntries(COLUMNS.map((col) => [col.key, []]));
  for (const task of tasks) buckets[columnFor(task.status)].push(task);

  // Phone: one column at a time, navigated by a horizontal tab strip.
  const [activeCol, setActiveCol] = useState<ColumnKey>('up_next');
  if (narrow) {
    const active = COLUMNS.find((col) => col.key === activeCol) ?? COLUMNS[0];
    return (
      <View style={s.mobileBoard}>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={s.colTabs}
          style={s.colTabsScroll}
        >
          {COLUMNS.map((col) => {
            const on = col.key === active.key;
            return (
              <Pressable
                key={col.key}
                onPress={() => setActiveCol(col.key)}
                style={[s.colTab, on && s.colTabOn]}
              >
                <Text style={[s.colTabText, on && s.colTabTextOn]}>{col.label}</Text>
                <Text style={[s.colTabCount, on && s.colTabCountOn]}>{buckets[col.key].length}</Text>
              </Pressable>
            );
          })}
        </ScrollView>
        <View style={s.mobileColumn}>
          {active.key === 'whiteboard' && <WhiteboardCapture ownerId={ownerId} />}
          <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={s.columnBody}>
            {buckets[active.key].length === 0 ? (
              <Text style={s.columnEmpty}>Nothing here yet.</Text>
            ) : (
              buckets[active.key].map((task) => (
                <TaskCard key={task.id} task={task} ownerId={ownerId} onEdit={onEdit} />
              ))
            )}
          </ScrollView>
        </View>
      </View>
    );
  }

  return (
    <View style={s.columns}>
      {COLUMNS.map((col) => (
        <View key={col.key} style={s.column}>
          <View style={s.columnHead}>
            <Text style={s.columnTitle}>{col.label}</Text>
            <Text style={s.columnCount}>{buckets[col.key].length}</Text>
          </View>
          {col.key === 'whiteboard' && <WhiteboardCapture ownerId={ownerId} />}
          <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={s.columnBody}>
            {buckets[col.key].length === 0 ? (
              <Text style={s.columnEmpty}>—</Text>
            ) : (
              buckets[col.key].map((task) => (
                <TaskCard key={task.id} task={task} ownerId={ownerId} onEdit={onEdit} />
              ))
            )}
          </ScrollView>
        </View>
      ))}
    </View>
  );
}

function ListView({
  tasks, ownerId, onEdit,
}: { tasks: TaskOut[]; ownerId: 1 | 2; onEdit: (task: TaskOut) => void }) {
  const buckets: Record<string, TaskOut[]> = Object.fromEntries(COLUMNS.map((col) => [col.key, []]));
  for (const task of tasks) buckets[columnFor(task.status)].push(task);

  return (
    <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={{ maxWidth: 560 }}>
      {COLUMNS.map((col) =>
        buckets[col.key].length === 0 ? null : (
          <View key={col.key} style={s.listSection}>
            <Text style={s.listSectionHead}>
              {col.label} · {buckets[col.key].length}
            </Text>
            {buckets[col.key].map((task) => (
              <TaskCard key={task.id} task={task} ownerId={ownerId} onEdit={onEdit} />
            ))}
          </View>
        ),
      )}
    </ScrollView>
  );
}

/**
 * Task popover — handles both creating a new task and editing an existing
 * one. When `editingTask` is set, the form is pre-populated with that task's
 * values and Save calls PATCH /tasks/{id}; when omitted, Submit creates a
 * new pending task (plus any staged subtasks) via POST /tasks.
 *
 * Backdrop-click closes; Esc-equivalent is the ✕ in the corner. Submit is
 * disabled until there's a title.
 */
function TaskModal({
  ownerId, editingTask, onClose,
}: {
  ownerId: 1 | 2;
  editingTask?: TaskOut;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const isEdit = !!editingTask;

  const [title, setTitle] = useState(editingTask?.title ?? '');
  const [description, setDescription] = useState(editingTask?.description ?? '');
  const [mins, setMins] = useState(String(editingTask?.est_minutes ?? 25));
  const [importance, setImportance] = useState(editingTask?.importance ?? 5);
  // Who the task is assigned to — defaults to the existing task's owner when
  // editing, or to the dashboard's currently-viewed owner when creating.
  const [assignedTo, setAssignedTo] = useState<1 | 2>(
    ((editingTask?.owner_id ?? ownerId) as 1 | 2)
  );
  // YYYY-MM-DD; sliced from the ISO string if editing.
  const [deadline, setDeadline] = useState(
    editingTask?.deadline ? editingTask.deadline.slice(0, 10) : ''
  );
  const [recurrence, setRecurrence] = useState<'none' | 'daily' | 'weekly' | 'monthly'>(
    (editingTask?.recurrence as 'daily' | 'weekly' | 'monthly' | null) ?? 'none'
  );
  const [subtasks, setSubtasks] = useState<string[]>([]);  // staged subtasks (create mode only)
  const [newSubtask, setNewSubtask] = useState('');

  const invalidateBoards = () => {
    // Invalidate both the current viewer's board and the assignee's board so
    // a cross-cofounder assignment shows up immediately on whichever side is
    // being looked at.
    qc.invalidateQueries({ queryKey: ['tasks', ownerId] });
    qc.invalidateQueries({ queryKey: ['next-action', ownerId] });
    if (assignedTo !== ownerId) {
      qc.invalidateQueries({ queryKey: ['tasks', assignedTo] });
      qc.invalidateQueries({ queryKey: ['next-action', assignedTo] });
    }
    if (editingTask && editingTask.owner_id !== assignedTo) {
      qc.invalidateQueries({ queryKey: ['tasks', editingTask.owner_id] });
      qc.invalidateQueries({ queryKey: ['next-action', editingTask.owner_id] });
    }
  };

  const create = useMutation({
    mutationFn: async () => {
      // Convert local YYYY-MM-DD to ISO at end-of-day so "due May 5" really means
      // anytime that day, not midnight UTC = afternoon-before-locally.
      const deadlineIso = deadline
        ? new Date(`${deadline}T23:59:59`).toISOString()
        : undefined;
      const task = await api.createTask(assignedTo, title.trim(), {
        estMinutes: parseInt(mins, 10) || 25,
        importance,
        description: description.trim() || undefined,
        deadline: deadlineIso,
        ...(recurrence !== 'none' ? { recurrence } : {}),
      });
      // Subtasks added one at a time; server preserves order via `position`.
      for (let i = 0; i < subtasks.length; i++) {
        await api.createSubtask(task.id, subtasks[i], i);
      }
      return task;
    },
    onSuccess: () => { invalidateBoards(); onClose(); },
  });

  const update = useMutation({
    mutationFn: async () => {
      const deadlineIso = deadline
        ? new Date(`${deadline}T23:59:59`).toISOString()
        : undefined;
      const currentRec = (editingTask!.recurrence ?? 'none') as
        'none' | 'daily' | 'weekly' | 'monthly';
      return api.patchTask(editingTask!.id, {
        title: title.trim(),
        description: description.trim() || undefined,
        est_minutes: parseInt(mins, 10) || 25,
        importance,
        ...(deadlineIso ? { deadline: deadlineIso } : {}),
        ...(assignedTo !== editingTask!.owner_id ? { owner_id: assignedTo } : {}),
        ...(recurrence !== currentRec ? { recurrence } : {}),
      });
    },
    onSuccess: () => { invalidateBoards(); onClose(); },
  });

  const busy = isEdit ? update.isPending : create.isPending;
  const canSubmit = title.trim().length > 0 && !busy;
  const submit = () => {
    if (!canSubmit) return;
    isEdit ? update.mutate() : create.mutate();
  };

  const addSubtask = () => {
    const trimmed = newSubtask.trim();
    if (!trimmed) return;
    setSubtasks((prev) => [...prev, trimmed]);
    setNewSubtask('');
  };
  const removeSubtask = (idx: number) =>
    setSubtasks((prev) => prev.filter((_, i) => i !== idx));

  return (
    <View style={s.modalBackdrop}>
      {/* Backdrop is its own pressable so the click area only covers the dim outside */}
      <Pressable style={StyleSheet.absoluteFill} onPress={onClose} />
      <View style={s.modal}>
        <View style={s.modalHead}>
          <Text style={s.modalTitle}>{isEdit ? 'Edit Task' : 'New Task'}</Text>
          <Pressable onPress={onClose} hitSlop={8}>
            <Text style={s.modalClose}>✕</Text>
          </Pressable>
        </View>

        <ScrollView style={s.modalBody} contentContainerStyle={{ gap: sp.md }}>
          {/* Assign to */}
          <View style={s.field}>
            <Text style={s.fieldLabel}>ASSIGN TO</Text>
            <OwnerSwitcher active={assignedTo} onChange={setAssignedTo} />
          </View>

          {/* Title */}
          <View style={s.field}>
            <Text style={s.fieldLabel}>TITLE</Text>
            <TextInput
              value={title}
              onChangeText={setTitle}
              placeholder="what's the task?"
              placeholderTextColor={c.textFaint}
              style={s.input}
              autoFocus
              returnKeyType="next"
            />
          </View>

          {/* Description */}
          <View style={s.field}>
            <Text style={s.fieldLabel}>DESCRIPTION</Text>
            <TextInput
              value={description}
              onChangeText={setDescription}
              placeholder="optional context, links, anything you'd want to remember"
              placeholderTextColor={c.textFaint}
              style={[s.input, s.inputMultiline]}
              multiline
              numberOfLines={3}
            />
          </View>

          {/* Time + Priority row */}
          <View style={s.row}>
            <View style={[s.field, { flex: 0, width: 120 }]}>
              <Text style={s.fieldLabel}>ESTIMATE</Text>
              <View style={s.minsRow}>
                <TextInput
                  value={mins}
                  onChangeText={(v) => setMins(v.replace(/[^0-9]/g, ''))}
                  placeholder="25"
                  placeholderTextColor={c.textFaint}
                  style={[s.input, { width: 60, textAlign: 'center' }]}
                  inputMode="numeric"
                />
                <Text style={s.unitLabel}>min</Text>
              </View>
            </View>
            <View style={[s.field, { flex: 1 }]}>
              <Text style={s.fieldLabel}>PRIORITY (1 = low, 10 = critical)</Text>
              <View style={s.priorityRow}>
                {[1,2,3,4,5,6,7,8,9,10].map((n) => (
                  <Pressable
                    key={n}
                    onPress={() => setImportance(n)}
                    style={({ pressed }) => [
                      s.priorityBtn,
                      importance === n && s.priorityBtnOn,
                      pressed && { opacity: 0.85 },
                    ]}
                  >
                    <Text style={[s.priorityBtnText, importance === n && s.priorityBtnTextOn]}>
                      {n}
                    </Text>
                  </Pressable>
                ))}
              </View>
            </View>
          </View>

          {/* Deadline — native calendar picker on web */}
          <View style={s.field}>
            <Text style={s.fieldLabel}>DEADLINE (optional)</Text>
            <DateField
              value={deadline}
              onChange={setDeadline}
              style={[s.input, { width: 200 }]}
            />
          </View>

          {/* Repeats */}
          <View style={s.field}>
            <Text style={s.fieldLabel}>REPEATS</Text>
            <View style={s.recurrenceRow}>
              {(['none', 'daily', 'weekly', 'monthly'] as const).map((option) => (
                <Pressable
                  key={option}
                  onPress={() => setRecurrence(option)}
                  style={({ pressed }) => [
                    s.recurrenceBtn,
                    recurrence === option && s.recurrenceBtnOn,
                    pressed && { opacity: 0.85 },
                  ]}
                >
                  <Text style={[s.recurrenceBtnText, recurrence === option && s.recurrenceBtnTextOn]}>
                    {option === 'none' ? 'No repeat' : option.charAt(0).toUpperCase() + option.slice(1)}
                  </Text>
                </Pressable>
              ))}
            </View>
          </View>

          {/* Subtasks — only stageable when creating. When editing, subtask
              add/delete is done from the card (tap the chevron to expand). */}
          {!isEdit && (
            <View style={s.field}>
              <Text style={s.fieldLabel}>SUBTASKS</Text>
              {subtasks.length > 0 && (
                <View style={s.subtaskList}>
                  {subtasks.map((sub, i) => (
                    <View key={i} style={s.subtaskRow}>
                      <Text style={s.subtaskBullet}>•</Text>
                      <Text style={s.subtaskText} numberOfLines={1}>{sub}</Text>
                      <Pressable onPress={() => removeSubtask(i)} hitSlop={6}>
                        <Text style={s.subtaskDelete}>✕</Text>
                      </Pressable>
                    </View>
                  ))}
                </View>
              )}
              <View style={s.subtaskInputRow}>
                <TextInput
                  value={newSubtask}
                  onChangeText={setNewSubtask}
                  onSubmitEditing={addSubtask}
                  placeholder="+ add a step (Enter to add another)"
                  placeholderTextColor={c.textFaint}
                  style={[s.input, { flex: 1 }]}
                  returnKeyType="done"
                  blurOnSubmit={false}
                />
                <Pressable
                  onPress={addSubtask}
                  disabled={!newSubtask.trim()}
                  style={({ pressed }) => [
                    s.subtaskAddBtn,
                    !newSubtask.trim() && { opacity: 0.4 },
                    pressed && { opacity: 0.85 },
                  ]}
                >
                  <Text style={s.subtaskAddBtnText}>ADD</Text>
                </Pressable>
              </View>
            </View>
          )}
        </ScrollView>

        {/* Footer: Cancel + (Save | Add Task) */}
        <View style={s.modalFoot}>
          <Pressable onPress={onClose} style={s.cancelBtn}>
            <Text style={s.cancelBtnText}>Cancel</Text>
          </Pressable>
          <Pressable
            onPress={submit}
            disabled={!canSubmit}
            style={({ pressed }) => [
              s.submitBtn,
              !canSubmit && s.submitBtnDisabled,
              pressed && canSubmit && { opacity: 0.85 },
            ]}
          >
            <Text style={[s.submitBtnText, !canSubmit && { color: c.textFaint }]}>
              {busy
                ? isEdit ? 'SAVING…' : 'CREATING…'
                : isEdit ? 'SAVE' : '+ ADD TASK'}
            </Text>
          </Pressable>
        </View>
      </View>
    </View>
  );
}

/** Friendly empty board with a clear CTA to add the first task. */
function EmptyBoard({ ownerId: _o, onAdd }: { ownerId: 1 | 2; onAdd: () => void }) {
  return (
    <View style={s.emptyState}>
      <Text style={s.emptyTitle}>Clean slate.</Text>
      <Text style={s.emptyBody}>
        Nothing on the board yet. Add a task to get started, or drop a fuzzy goal
        into the White Board column and decompose it later.
      </Text>
      <Pressable
        onPress={onAdd}
        style={({ pressed }) => [s.emptyCta, pressed && { opacity: 0.85 }]}
      >
        <Text style={s.emptyCtaText}>+ ADD A TASK</Text>
      </Pressable>
    </View>
  );
}

/**
 * Rapid idea capture for the White Board column. Enter creates a parked task
 * (status=whiteboard) — no calendar block, scheduler ignores it until promoted.
 */
function WhiteboardCapture({ ownerId }: { ownerId: 1 | 2 }) {
  const qc = useQueryClient();
  const [text, setText] = useState('');
  const add = useMutation({
    mutationFn: (title: string) => api.createTask(ownerId, title, { status: 'whiteboard' }),
    onSuccess: () => {
      setText('');
      qc.invalidateQueries({ queryKey: ['tasks', ownerId] });
    },
  });
  const submit = () => {
    const t = text.trim();
    if (t) add.mutate(t);
  };
  return (
    <TextInput
      value={text}
      onChangeText={setText}
      onSubmitEditing={submit}
      placeholder="+ dump an idea"
      placeholderTextColor={c.textFaint}
      style={s.capture}
      returnKeyType="done"
      blurOnSubmit={false}
    />
  );
}

function ViewTab({ label, on, onPress }: { label: string; on: boolean; onPress: () => void }) {
  return (
    <Text
      onPress={onPress}
      style={[s.viewTab, on && s.viewTabOn]}
      suppressHighlighting
    >
      {label}
    </Text>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: c.bg },
  topbar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: sp.lg,
    paddingVertical: sp.md,
    borderBottomWidth: 1,
    borderBottomColor: c.border,
  },
  topbarNarrow: {
    flexDirection: 'column',
    alignItems: 'stretch',
    gap: sp.sm,
  },
  brandRow: { flexDirection: 'row', alignItems: 'center', gap: sp.sm, flexShrink: 1 },
  logoDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: c.accent },
  brand: { ...t.hud, color: c.text, flexShrink: 1 },
  brandSub: { ...t.hud, color: c.textFaint },
  topbarRight: { flexDirection: 'row', alignItems: 'center', gap: sp.lg },
  topbarRightNarrow: { flexWrap: 'wrap', rowGap: sp.sm, gap: sp.md },
  viewToggle: {
    flexDirection: 'row',
    borderWidth: 1,
    borderColor: c.border,
    borderRadius: r.md,
    overflow: 'hidden',
  },
  viewTab: {
    ...t.duration,
    color: c.textDim,
    paddingHorizontal: sp.md,
    paddingVertical: sp.xs,
  },
  viewTabOn: { backgroundColor: c.surface, color: c.accent },
  signOut: { ...t.duration, color: c.textFaint },
  navLink: { ...t.duration, color: c.textDim },

  // "+ NEW TASK" button in top bar
  newTaskTrigger: {
    borderWidth: 1,
    borderColor: c.accent,
    borderRadius: r.md,
    paddingHorizontal: sp.md,
    paddingVertical: sp.xs,
  },
  newTaskTriggerText: { ...t.duration, color: c.accent },

  // New-task popover modal
  modalBackdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(0,0,0,0.55)',
    alignItems: 'center',
    justifyContent: 'center',
    padding: sp.lg,
    zIndex: 100,
  },
  modal: {
    width: '100%',
    maxWidth: 640,
    maxHeight: '90%',
    backgroundColor: c.surface,
    borderRadius: r.lg,
    borderWidth: 1,
    borderColor: c.border,
    overflow: 'hidden',
  },
  modalHead: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: sp.lg,
    paddingVertical: sp.md,
    borderBottomWidth: 1,
    borderBottomColor: c.border,
  },
  modalTitle: { ...t.hud, color: c.accent, fontSize: 14 },
  modalClose: { ...t.subtask, color: c.textDim, fontSize: 18 },
  modalBody: { paddingHorizontal: sp.lg, paddingVertical: sp.md },
  modalFoot: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: sp.sm,
    paddingHorizontal: sp.lg,
    paddingVertical: sp.md,
    borderTopWidth: 1,
    borderTopColor: c.border,
    backgroundColor: c.bg,
  },

  field: { gap: sp.xs },
  fieldLabel: { ...t.micro, color: c.textFaint },
  input: {
    ...t.subtask,
    color: c.text,
    backgroundColor: c.bg,
    borderRadius: r.sm,
    borderWidth: 1,
    borderColor: c.border,
    paddingHorizontal: sp.sm,
    paddingVertical: sp.xs,
    outlineStyle: 'none' as any,
  },
  inputMultiline: { minHeight: 72, textAlignVertical: 'top' as any, paddingVertical: sp.sm },
  row: { flexDirection: 'row', gap: sp.md, alignItems: 'flex-start' },
  minsRow: { flexDirection: 'row', alignItems: 'center', gap: sp.sm },
  unitLabel: { ...t.taskMeta, color: c.textDim },

  priorityRow: { flexDirection: 'row', gap: 4, flexWrap: 'wrap' },
  priorityBtn: {
    minWidth: 30,
    paddingHorizontal: sp.xs,
    paddingVertical: sp.xs,
    borderRadius: r.sm,
    borderWidth: 1,
    borderColor: c.border,
    backgroundColor: c.bg,
    alignItems: 'center',
  },
  priorityBtnOn: { backgroundColor: c.accent, borderColor: c.accent },
  priorityBtnText: { ...t.duration, color: c.textDim },
  priorityBtnTextOn: { color: c.textOnAccent },

  recurrenceRow: { flexDirection: 'row', gap: sp.xs, flexWrap: 'wrap' },
  recurrenceBtn: {
    paddingHorizontal: sp.md,
    paddingVertical: sp.xs,
    borderRadius: r.sm,
    borderWidth: 1,
    borderColor: c.border,
    backgroundColor: c.bg,
  },
  recurrenceBtnOn: { backgroundColor: c.accent, borderColor: c.accent },
  recurrenceBtnText: { ...t.duration, color: c.textDim },
  recurrenceBtnTextOn: { color: c.textOnAccent },

  subtaskList: { gap: 2, marginBottom: sp.xs },
  subtaskRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: sp.sm,
    paddingVertical: 3,
    paddingHorizontal: sp.sm,
    backgroundColor: c.bg,
    borderRadius: r.sm,
  },
  subtaskBullet: { ...t.subtask, color: c.accent },
  subtaskText: { ...t.subtask, color: c.text, flex: 1 },
  subtaskDelete: { ...t.taskMeta, color: c.textDim, paddingHorizontal: sp.xs },
  subtaskInputRow: { flexDirection: 'row', gap: sp.sm, alignItems: 'center' },
  subtaskAddBtn: {
    borderWidth: 1,
    borderColor: c.border,
    borderRadius: r.sm,
    paddingHorizontal: sp.md,
    paddingVertical: 6,
  },
  subtaskAddBtnText: { ...t.duration, color: c.textDim },

  cancelBtn: { paddingHorizontal: sp.lg, paddingVertical: sp.sm, borderRadius: r.sm },
  cancelBtnText: { ...t.button, color: c.textDim },
  submitBtn: {
    backgroundColor: c.accent,
    borderRadius: r.sm,
    paddingHorizontal: sp.xl,
    paddingVertical: sp.sm,
  },
  submitBtnDisabled: { backgroundColor: c.surfaceElevated },
  submitBtnText: { ...t.button, color: c.textOnAccent },

  // Empty-state CTA
  emptyState: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: sp.xl,
    gap: sp.sm,
  },
  emptyTitle: { ...t.taskTitle, color: c.text, fontSize: 18 },
  emptyBody: {
    ...t.taskMeta,
    color: c.textDim,
    textAlign: 'center',
    maxWidth: 380,
    marginBottom: sp.md,
  },
  emptyCta: {
    backgroundColor: c.accent,
    paddingHorizontal: sp.xl,
    paddingVertical: sp.md,
    borderRadius: r.md,
  },
  emptyCtaText: { ...t.button, color: c.textOnAccent },

  body: { flex: 1, flexDirection: 'row' },
  bodyNarrow: { flexDirection: 'column' },
  main: { flex: 1, padding: sp.lg },
  mainNarrow: { padding: sp.md },
  sidebar: {
    width: 320,
    padding: sp.lg,
    borderLeftWidth: 1,
    borderLeftColor: c.border,
    backgroundColor: c.bg,
  },
  sidebarHeading: { ...t.hud, color: c.accent, marginBottom: sp.md },

  // Phone single-column board
  mobileBoard: { flex: 1, gap: sp.sm },
  colTabsScroll: { flexGrow: 0 },
  colTabs: { flexDirection: 'row', gap: sp.xs, paddingBottom: sp.xs },
  colTab: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: sp.xs,
    paddingHorizontal: sp.md,
    paddingVertical: sp.sm,
    borderRadius: r.pill,
    borderWidth: 1,
    borderColor: c.border,
    backgroundColor: '#0f141b',
  },
  colTabOn: { borderColor: c.accent, backgroundColor: c.surface },
  colTabText: { ...t.duration, color: c.textDim },
  colTabTextOn: { color: c.accent },
  colTabCount: { ...t.micro, color: c.textFaint },
  colTabCountOn: { color: c.accent },
  mobileColumn: {
    flex: 1,
    backgroundColor: '#0f141b',
    borderRadius: r.lg,
    borderWidth: 1,
    borderColor: c.border,
    padding: sp.sm,
  },

  columns: { flex: 1, flexDirection: 'row', gap: sp.md },
  column: {
    flex: 1,
    backgroundColor: '#0f141b',
    borderRadius: r.lg,
    borderWidth: 1,
    borderColor: c.border,
    padding: sp.sm,
  },
  columnHead: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: sp.xs,
    paddingBottom: sp.sm,
  },
  columnTitle: { ...t.hud, color: c.textDim },
  columnCount: { ...t.duration, color: c.textFaint },
  columnBody: { paddingBottom: sp.lg },
  capture: {
    ...t.taskMeta,
    color: c.text,
    backgroundColor: c.bg,
    borderRadius: r.sm,
    borderWidth: 1,
    borderColor: c.border,
    paddingHorizontal: sp.sm,
    paddingVertical: sp.xs,
    marginBottom: sp.sm,
    outlineStyle: 'none' as any,
  },
  columnEmpty: { ...t.taskMeta, color: c.textFaint, textAlign: 'center', paddingVertical: sp.md },

  listSection: { marginBottom: sp.lg },
  listSectionHead: { ...t.hud, color: c.textDim, marginBottom: sp.sm },

  muted: { ...t.taskMeta, color: c.textDim },
});
