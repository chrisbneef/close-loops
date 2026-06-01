/**
 * Compact task card for the Kanban board + the dashboard right sidebar.
 * Shows title, meta (importance / est / subtask progress / deadline), a
 * contextual click-to-move control, and an expandable SOP subtask checklist.
 *
 * Widget-themed (dark slate + lime). The move control offers only the
 * transitions valid from the card's current column.
 */

import { useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api, type TaskOut } from '@/src/api';
import { ColumnKey, columnFor, useTaskMove } from '@/src/components/move-task';
import {
  widgetColors as c, widgetRadii as r, widgetSpacing as sp, widgetType as t,
} from '@/src/widget-theme';

function formatDuration(min: number): string {
  if (min < 60) return `${min}m`;
  const h = Math.floor(min / 60);
  const m = min % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

function deadlineLabel(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

export function TaskCard({
  task, ownerId, onEdit,
}: {
  task: TaskOut;
  ownerId: 1 | 2;
  onEdit?: (task: TaskOut) => void;
}) {
  const qc = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [askReason, setAskReason] = useState(false);
  const [reason, setReason] = useState('');
  const move = useTaskMove(ownerId);
  const col = columnFor(task.status);

  const toggleSub = useMutation({
    mutationFn: ({ subId, completed }: { subId: number; completed: boolean }) =>
      api.toggleSubtask(task.id, subId, completed),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tasks', ownerId] }),
  });

  const subDone = task.subtasks.filter((sub) => sub.completed).length;
  const subTotal = task.subtasks.length;
  const dl = deadlineLabel(task.deadline);

  const doMove = (target: ColumnKey, r?: string) => move.mutate({ task, target, reason: r });
  const submitPause = () => {
    const txt = reason.trim();
    if (!txt) return;
    doMove('paused', txt);
    setAskReason(false);
    setReason('');
  };

  return (
    <View style={[s.card, col === 'in_progress' && s.cardActive]}>
      <View style={s.head}>
        <Pressable
          onPress={() => subTotal > 0 && setExpanded(!expanded)}
          style={s.headLeft}
        >
          {subTotal > 0 && <Text style={s.chevron}>{expanded ? '▾' : '▸'}</Text>}
          <Text style={s.title} numberOfLines={2}>{task.title}</Text>
        </Pressable>
        <Text style={s.dur}>{formatDuration(task.est_minutes)}</Text>
        {onEdit && (
          <Pressable
            onPress={() => onEdit(task)}
            hitSlop={6}
            style={({ pressed }) => [s.editBtn, pressed && { opacity: 0.6 }]}
          >
            <Text style={s.editIcon}>✎</Text>
          </Pressable>
        )}
      </View>

      <View style={s.meta}>
        <Text style={s.metaItem}>imp {task.importance}</Text>
        {subTotal > 0 && <Text style={s.metaItem}> · {subDone}/{subTotal}</Text>}
        {dl && <Text style={s.metaDeadline}> · {dl}</Text>}
      </View>

      {expanded && subTotal > 0 && (
        <View style={s.subs}>
          {task.subtasks.map((sub) => (
            <Pressable
              key={sub.id}
              onPress={() => toggleSub.mutate({ subId: sub.id, completed: !sub.completed })}
              style={s.subRow}
            >
              <Text style={[s.checkbox, sub.completed && s.checkboxOn]}>
                {sub.completed ? '◉' : '○'}
              </Text>
              <Text style={[s.subText, sub.completed && s.subTextDone]}>{sub.title}</Text>
            </Pressable>
          ))}
        </View>
      )}

      {askReason ? (
        <View style={s.reasonRow}>
          <TextInput
            value={reason}
            onChangeText={setReason}
            onSubmitEditing={submitPause}
            placeholder="why pause?"
            placeholderTextColor={c.textFaint}
            style={s.reasonInput}
            autoFocus
            returnKeyType="done"
          />
          <Pressable onPress={submitPause} style={[s.moveBtn, s.moveBtnPrimary]}>
            <Text style={[s.moveText, { color: c.textOnAccent }]}>OK</Text>
          </Pressable>
          <Pressable onPress={() => { setAskReason(false); setReason(''); }} style={s.moveBtn}>
            <Text style={s.moveText}>✕</Text>
          </Pressable>
        </View>
      ) : (
        <View style={s.moves}>
          {col === 'whiteboard' && (
            <MoveBtn label="→ Up Next" primary onPress={() => doMove('up_next')} />
          )}
          {col === 'up_next' && (
            <MoveBtn label="▶ Start" primary onPress={() => doMove('in_progress')} />
          )}
          {col === 'in_progress' && (
            <MoveBtn label="❚❚ Pause" onPress={() => setAskReason(true)} />
          )}
          {col === 'paused' && (
            <MoveBtn label="▶ Resume" primary onPress={() => doMove('in_progress')} />
          )}
          {(col === 'whiteboard' || col === 'up_next' || col === 'in_progress' || col === 'paused') && (
            <MoveBtn label="✓ Done" done onPress={() => doMove('done')} />
          )}
          {col === 'up_next' && (
            <MoveBtn label="⬚ Park" onPress={() => doMove('whiteboard')} />
          )}
          {(col === 'in_progress' || col === 'paused' || col === 'done') && (
            <MoveBtn label="↩" onPress={() => doMove('up_next')} />
          )}
        </View>
      )}
    </View>
  );
}

function MoveBtn({
  label, onPress, primary, done,
}: { label: string; onPress: () => void; primary?: boolean; done?: boolean }) {
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [
        s.moveBtn,
        primary && s.moveBtnPrimary,
        done && s.moveBtnDone,
        pressed && { opacity: 0.8 },
      ]}
    >
      <Text style={[s.moveText, (primary || done) && { color: c.textOnAccent }]}>{label}</Text>
    </Pressable>
  );
}

const s = StyleSheet.create({
  card: {
    backgroundColor: c.surface,
    borderRadius: r.md,
    borderWidth: 1,
    borderColor: c.border,
    padding: sp.sm,
    marginBottom: sp.sm,
    gap: sp.xs,
  },
  cardActive: { borderColor: c.borderActive },
  head: { flexDirection: 'row', alignItems: 'flex-start', gap: sp.xs },
  headLeft: { flexDirection: 'row', alignItems: 'flex-start', gap: sp.xs, flex: 1 },
  chevron: { color: c.textFaint, fontSize: 11, marginTop: 2 },
  title: { ...t.taskTitle, color: c.text, flex: 1 },
  dur: { ...t.duration, color: c.textDim },
  editBtn: { paddingHorizontal: 2, marginLeft: 2 },
  editIcon: { ...t.duration, color: c.textFaint, fontSize: 14 },
  meta: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center' },
  metaItem: { ...t.taskMeta, color: c.textDim },
  metaDeadline: { ...t.taskMeta, color: c.warning },
  subs: { gap: 2, paddingLeft: sp.md, paddingTop: sp.xs },
  subRow: { flexDirection: 'row', alignItems: 'center', gap: sp.xs },
  checkbox: { color: c.textFaint, fontSize: 13 },
  checkboxOn: { color: c.done },
  subText: { ...t.subtask, color: c.text, flex: 1 },
  subTextDone: { color: c.textFaint, textDecorationLine: 'line-through' },
  moves: { flexDirection: 'row', flexWrap: 'wrap', gap: sp.xs, marginTop: sp.xs },
  moveBtn: {
    paddingHorizontal: sp.sm,
    paddingVertical: 5,
    borderRadius: r.sm,
    borderWidth: 1,
    borderColor: c.border,
  },
  moveBtnPrimary: { backgroundColor: c.accent, borderColor: c.accent },
  moveBtnDone: { backgroundColor: c.done, borderColor: c.done },
  moveText: { ...t.duration, color: c.textDim },
  reasonRow: { flexDirection: 'row', alignItems: 'center', gap: sp.xs, marginTop: sp.xs },
  reasonInput: {
    ...t.subtask,
    flex: 1,
    color: c.text,
    backgroundColor: c.bg,
    borderRadius: r.sm,
    paddingHorizontal: sp.sm,
    paddingVertical: 5,
    borderWidth: 1,
    borderColor: c.border,
    outlineStyle: 'none' as any,
  },
});
