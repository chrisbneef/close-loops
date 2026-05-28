/**
 * Michael / Chris owner toggle, widget-themed. Shared by the dashboard top bar
 * (and a candidate to replace the inline copies in widget.tsx / index.tsx later).
 */

import { Pressable, StyleSheet, Text, View } from 'react-native';

import {
  widgetColors as c, widgetRadii as r, widgetSpacing as sp, widgetType as t,
} from '@/src/widget-theme';

export const OWNERS = [
  { id: 1, name: 'Michael' },
  { id: 2, name: 'Chris' },
] as const;

export function OwnerSwitcher({
  active, onChange,
}: { active: 1 | 2; onChange: (id: 1 | 2) => void }) {
  return (
    <View style={s.row}>
      {OWNERS.map((o) => {
        const on = active === o.id;
        return (
          <Pressable
            key={o.id}
            onPress={() => onChange(o.id)}
            style={({ pressed }) => [s.pill, on && s.pillActive, pressed && { opacity: 0.7 }]}
          >
            <Text style={[s.text, on && s.textActive]}>{o.name}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const s = StyleSheet.create({
  row: { flexDirection: 'row', gap: sp.xs },
  pill: {
    paddingHorizontal: sp.md,
    paddingVertical: sp.xs,
    borderRadius: r.pill,
    borderWidth: 1,
    borderColor: c.border,
  },
  pillActive: { backgroundColor: c.surface, borderColor: c.accent },
  text: { ...t.duration, color: c.textDim },
  textActive: { color: c.accent },
});
