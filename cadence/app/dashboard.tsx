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
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { useQuery } from '@tanstack/react-query';

import { api, type TaskOut } from '@/src/api';
import { OwnerSwitcher } from '@/src/components/OwnerSwitcher';
import { TaskCard } from '@/src/components/TaskCard';
import { COLUMNS, columnFor } from '@/src/components/move-task';
import {
  widgetColors as c, widgetRadii as r, widgetSpacing as sp, widgetType as t,
} from '@/src/widget-theme';

type ViewMode = 'kanban' | 'list';

export default function DashboardScreen() {
  const [ownerId, setOwnerId] = useState<1 | 2>(1);
  const [view, setView] = useState<ViewMode>('kanban');

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
      <View style={s.topbar}>
        <View style={s.brandRow}>
          <View style={s.logoDot} />
          <Text style={s.brand}>CLOSE YOUR LOOPS NOOB</Text>
          <Text style={s.brandSub}>· dashboard</Text>
        </View>
        <View style={s.topbarRight}>
          <OwnerSwitcher active={ownerId} onChange={setOwnerId} />
          <View style={s.viewToggle}>
            <ViewTab label="KANBAN" on={view === 'kanban'} onPress={() => setView('kanban')} />
            <ViewTab label="LIST" on={view === 'list'} onPress={() => setView('list')} />
          </View>
        </View>
      </View>

      {/* Body: main area + right sidebar */}
      <View style={s.body}>
        <View style={s.main}>
          {tasksQuery.isLoading ? (
            <Text style={s.muted}>Loading…</Text>
          ) : tasksQuery.isError ? (
            <Text style={s.muted}>Can't reach the brain at localhost:8000.</Text>
          ) : tasks.length === 0 ? (
            <Text style={s.muted}>No tasks for this user. Switch owner or add one.</Text>
          ) : view === 'kanban' ? (
            <KanbanBoard tasks={tasks} ownerId={ownerId} />
          ) : (
            <ListView tasks={tasks} ownerId={ownerId} />
          )}
        </View>

        <View style={s.sidebar}>
          <Text style={s.sidebarHeading}>TODAY</Text>
          {nextQuery.data?.current ? (
            <ScrollView showsVerticalScrollIndicator={false}>
              {[nextQuery.data.current, ...nextQuery.data.up_next].map((task) => (
                <TaskCard key={task.id} task={task} ownerId={ownerId} />
              ))}
            </ScrollView>
          ) : (
            <Text style={s.muted}>Nothing scheduled right now.</Text>
          )}
        </View>
      </View>
    </View>
  );
}

function KanbanBoard({ tasks, ownerId }: { tasks: TaskOut[]; ownerId: 1 | 2 }) {
  const buckets: Record<string, TaskOut[]> = { up_next: [], in_progress: [], paused: [], done: [] };
  for (const task of tasks) buckets[columnFor(task.status)].push(task);

  return (
    <View style={s.columns}>
      {COLUMNS.map((col) => (
        <View key={col.key} style={s.column}>
          <View style={s.columnHead}>
            <Text style={s.columnTitle}>{col.label}</Text>
            <Text style={s.columnCount}>{buckets[col.key].length}</Text>
          </View>
          <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={s.columnBody}>
            {buckets[col.key].length === 0 ? (
              <Text style={s.columnEmpty}>—</Text>
            ) : (
              buckets[col.key].map((task) => (
                <TaskCard key={task.id} task={task} ownerId={ownerId} />
              ))
            )}
          </ScrollView>
        </View>
      ))}
    </View>
  );
}

function ListView({ tasks, ownerId }: { tasks: TaskOut[]; ownerId: 1 | 2 }) {
  const buckets: Record<string, TaskOut[]> = { up_next: [], in_progress: [], paused: [], done: [] };
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
              <TaskCard key={task.id} task={task} ownerId={ownerId} />
            ))}
          </View>
        ),
      )}
    </ScrollView>
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
  brandRow: { flexDirection: 'row', alignItems: 'center', gap: sp.sm },
  logoDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: c.accent },
  brand: { ...t.hud, color: c.text },
  brandSub: { ...t.hud, color: c.textFaint },
  topbarRight: { flexDirection: 'row', alignItems: 'center', gap: sp.lg },
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

  body: { flex: 1, flexDirection: 'row' },
  main: { flex: 1, padding: sp.lg },
  sidebar: {
    width: 320,
    padding: sp.lg,
    borderLeftWidth: 1,
    borderLeftColor: c.border,
    backgroundColor: c.bg,
  },
  sidebarHeading: { ...t.hud, color: c.accent, marginBottom: sp.md },

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
  columnEmpty: { ...t.taskMeta, color: c.textFaint, textAlign: 'center', paddingVertical: sp.md },

  listSection: { marginBottom: sp.lg },
  listSectionHead: { ...t.hud, color: c.textDim, marginBottom: sp.sm },

  muted: { ...t.taskMeta, color: c.textDim },
});
