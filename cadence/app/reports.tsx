/**
 * Reports screen — daily / weekly memo-style retrospective. The memo (written
 * by Claude) is the hero: "here's what you accomplished, here's what slipped,
 * here's your biggest distraction." Below it, the hard numbers + the list of
 * what didn't get done. Widget-themed (dark slate + lime).
 *
 * One fetch per view (memo included), no auto-refetch — reports are on-demand,
 * so we don't burn an LLM call on a timer.
 */

import { useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Link } from 'expo-router';
import { useQuery } from '@tanstack/react-query';

import { api, type OpenTaskRow, type PeriodReport } from '@/src/api';
import { useAuth } from '@/src/auth-store';
import { OwnerSwitcher } from '@/src/components/OwnerSwitcher';
import {
  widgetColors as c, widgetRadii as r, widgetSpacing as sp, widgetType as t,
} from '@/src/widget-theme';

type Granularity = 'daily' | 'weekly';

function fmtMinutes(min: number): string {
  if (!min) return '0m';
  const h = Math.floor(min / 60);
  const m = min % 60;
  return h ? (m ? `${h}h ${m}m` : `${h}h`) : `${m}m`;
}

export default function ReportsScreen() {
  const authUserId = useAuth((s) => s.user?.id ?? 1) as 1 | 2;
  const logout = useAuth((s) => s.logout);
  const [ownerId, setOwnerId] = useState<1 | 2>(authUserId);
  const [granularity, setGranularity] = useState<Granularity>('daily');

  const report = useQuery({
    queryKey: ['report', granularity, ownerId],
    queryFn: () => api.getReport(granularity, ownerId),
    refetchOnWindowFocus: false,
    staleTime: 5 * 60_000,
  });

  const data = report.data;

  return (
    <View style={s.root}>
      <View style={s.topbar}>
        <View style={s.brandRow}>
          <View style={s.logoDot} />
          <Text style={s.brand}>CLOSE YOUR LOOPS NOOB</Text>
          <Text style={s.brandSub}>· reports</Text>
        </View>
        <View style={s.topbarRight}>
          <Link href="/dashboard" style={s.navLink}>← board</Link>
          <OwnerSwitcher active={ownerId} onChange={setOwnerId} />
          <View style={s.toggle}>
            <Tab label="DAILY" on={granularity === 'daily'} onPress={() => setGranularity('daily')} />
            <Tab label="WEEKLY" on={granularity === 'weekly'} onPress={() => setGranularity('weekly')} />
          </View>
          <Pressable onPress={() => logout()} hitSlop={6}>
            <Text style={s.signOut}>SIGN OUT</Text>
          </Pressable>
        </View>
      </View>

      <ScrollView contentContainerStyle={s.body} showsVerticalScrollIndicator={false}>
        {/* Memo hero */}
        <View style={s.memoCard}>
          <Text style={s.memoLabel}>{granularity === 'daily' ? 'TODAY' : 'THIS WEEK'}</Text>
          {report.isLoading ? (
            <View style={s.memoLoading}>
              <ActivityIndicator color={c.accent} />
              <Text style={s.muted}>Reading your {granularity === 'daily' ? 'day' : 'week'}…</Text>
            </View>
          ) : report.isError ? (
            <Text style={s.muted}>Can't reach the brain at the API base.</Text>
          ) : (
            <Text style={s.memoText}>{data?.memo ?? '—'}</Text>
          )}
        </View>

        {data && !report.isLoading && (
          <>
            {/* Stats strip */}
            <View style={s.stats}>
              <Stat n={data.total_completed} label="completed" accent />
              <Stat n={data.completed_on_time} label="on time" />
              <Stat n={data.completed_late} label="late" warn={data.completed_late > 0} />
              <Stat text={fmtMinutes(data.total_minutes_actual)} label="focus" />
              <Stat n={data.total_pauses} label="pauses" />
            </View>

            {/* Didn't get done */}
            <Section title="DIDN'T GET DONE">
              {data.incomplete.length === 0 ? (
                <Text style={s.muted}>Nothing slipped. Clean slate.</Text>
              ) : (
                data.incomplete.map((row) => <OpenRow key={row.task_id} row={row} />)
              )}
            </Section>

            {/* Decayed (only if any — empty until decay-marking ships) */}
            {data.decayed.length > 0 && (
              <Section title="DECAYED / ABANDONED">
                {data.decayed.map((row) => <OpenRow key={row.task_id} row={row} />)}
              </Section>
            )}

            {/* Distraction */}
            {data.total_pauses > 0 && (
              <Section title="BIGGEST DISTRACTION">
                <Text style={s.distraction}>
                  {data.biggest_distraction}
                  <Text style={s.muted}>
                    {'  '}· {data.total_pauses} pause{data.total_pauses !== 1 ? 's' : ''},{' '}
                    {fmtMinutes(data.total_pause_minutes)} lost
                  </Text>
                </Text>
                {Object.entries(data.pause_reasons).map(([reason, n]) => (
                  <Text key={reason} style={s.reasonRow}>· {reason} ×{n}</Text>
                ))}
              </Section>
            )}

            {/* Completed list */}
            {data.rows.length > 0 && (
              <Section title="COMPLETED">
                {data.rows.map((row) => (
                  <View key={row.task_id} style={s.doneRow}>
                    <Text style={s.doneTitle} numberOfLines={1}>{row.title}</Text>
                    <Text style={s.doneMeta}>
                      {fmtMinutes(row.actual_minutes)}
                      {row.on_time === false ? '  late' : row.on_time === true ? '  ✓' : ''}
                    </Text>
                  </View>
                ))}
              </Section>
            )}
          </>
        )}
      </ScrollView>
    </View>
  );
}

function Stat({ n, text, label, accent, warn }: {
  n?: number; text?: string; label: string; accent?: boolean; warn?: boolean;
}) {
  return (
    <View style={s.stat}>
      <Text style={[s.statNum, accent && { color: c.accent }, warn && { color: c.warning }]}>
        {text ?? n}
      </Text>
      <Text style={s.statLabel}>{label}</Text>
    </View>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={s.section}>
      <Text style={s.sectionTitle}>{title}</Text>
      {children}
    </View>
  );
}

function OpenRow({ row }: { row: OpenTaskRow }) {
  return (
    <View style={s.openRow}>
      <Text style={s.openTitle} numberOfLines={1}>{row.title}</Text>
      {row.overdue && <Text style={s.overdueBadge}>OVERDUE</Text>}
      <Text style={s.openMeta}>imp {row.importance}</Text>
    </View>
  );
}

function Tab({ label, on, onPress }: { label: string; on: boolean; onPress: () => void }) {
  return (
    <Text onPress={onPress} suppressHighlighting style={[s.tab, on && s.tabOn]}>{label}</Text>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: c.bg },
  topbar: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: sp.lg, paddingVertical: sp.md,
    borderBottomWidth: 1, borderBottomColor: c.border, flexWrap: 'wrap', gap: sp.sm,
  },
  brandRow: { flexDirection: 'row', alignItems: 'center', gap: sp.sm },
  logoDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: c.accent },
  brand: { ...t.hud, color: c.text },
  brandSub: { ...t.hud, color: c.textFaint },
  topbarRight: { flexDirection: 'row', alignItems: 'center', gap: sp.md, flexWrap: 'wrap' },
  navLink: { ...t.duration, color: c.textDim },
  toggle: { flexDirection: 'row', borderWidth: 1, borderColor: c.border, borderRadius: r.md, overflow: 'hidden' },
  tab: { ...t.duration, color: c.textDim, paddingHorizontal: sp.md, paddingVertical: sp.xs },
  tabOn: { backgroundColor: c.surface, color: c.accent },
  signOut: { ...t.duration, color: c.textFaint },

  body: { padding: sp.lg, maxWidth: 760, width: '100%', alignSelf: 'center', gap: sp.lg },

  memoCard: {
    backgroundColor: c.surface, borderRadius: r.lg, borderWidth: 1, borderColor: c.border,
    padding: sp.lg, gap: sp.sm,
  },
  memoLabel: { ...t.hud, color: c.accent },
  memoLoading: { flexDirection: 'row', alignItems: 'center', gap: sp.sm, paddingVertical: sp.md },
  memoText: { fontFamily: 'Sora_400Regular', fontSize: 15, lineHeight: 24, color: c.text },

  stats: { flexDirection: 'row', flexWrap: 'wrap', gap: sp.lg },
  stat: { minWidth: 64 },
  statNum: { fontFamily: 'JetBrainsMono_700Bold', fontSize: 22, color: c.text },
  statLabel: { ...t.micro, color: c.textDim, marginTop: 2 },

  section: { gap: sp.xs },
  sectionTitle: { ...t.hud, color: c.textDim, marginBottom: sp.xs },

  openRow: { flexDirection: 'row', alignItems: 'center', gap: sp.sm, paddingVertical: 3 },
  openTitle: { ...t.subtask, color: c.text, flex: 1 },
  overdueBadge: {
    ...t.micro, color: c.bg, backgroundColor: c.warning,
    paddingHorizontal: sp.xs, paddingVertical: 1, borderRadius: r.sm, overflow: 'hidden',
  },
  openMeta: { ...t.duration, color: c.textFaint },

  distraction: { ...t.taskTitle, color: c.text },
  reasonRow: { ...t.taskMeta, color: c.textDim },

  doneRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingVertical: 3, gap: sp.sm },
  doneTitle: { ...t.subtask, color: c.textDim, flex: 1 },
  doneMeta: { ...t.duration, color: c.textFaint },

  muted: { ...t.taskMeta, color: c.textDim },
});
