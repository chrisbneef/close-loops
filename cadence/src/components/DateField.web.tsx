/**
 * Web-only DateField — opens an inline calendar popover when the trigger is
 * tapped. Backed by react-day-picker (web-only, ~7 KB gzip). Metro picks this
 * .web.tsx file when bundling for web; the native bundle uses DateField.tsx
 * (plain TextInput), so react-day-picker never ships to mobile.
 *
 * Format on the wire stays YYYY-MM-DD — same as the previous text input —
 * so existing serialize logic in the modals doesn't need to change.
 */

import { useState } from 'react';
import { Pressable, StyleProp, StyleSheet, Text, TextStyle, View } from 'react-native';
import { DayPicker } from 'react-day-picker';
import 'react-day-picker/style.css';

import {
  widgetColors as c, widgetRadii as r, widgetSpacing as sp, widgetType as t,
} from '@/src/widget-theme';

interface DateFieldProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  style?: StyleProp<TextStyle>;
}

function formatYMD(d: Date): string {
  // Use LOCAL components so a date picked in the user's timezone serializes
  // to the same date string they see — toISOString() would skew across
  // timezone boundaries.
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

function parseYMD(s: string): Date | undefined {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return undefined;
  const [y, m, d] = s.split('-').map(Number);
  return new Date(y, m - 1, d);
}

export function DateField({
  value, onChange, placeholder = 'Pick a date', style,
}: DateFieldProps) {
  const [open, setOpen] = useState(false);
  const selected = parseYMD(value);

  return (
    <View>
      <Pressable
        onPress={() => setOpen((o) => !o)}
        style={({ pressed }) => [
          s.trigger,
          style as object,
          pressed && { opacity: 0.85 },
        ]}
      >
        <Text style={[s.triggerText, !value && { color: c.textFaint }]}>
          {value || placeholder}
        </Text>
        {value ? (
          <Pressable
            onPress={(e) => { e.stopPropagation(); onChange(''); setOpen(false); }}
            hitSlop={6}
          >
            <Text style={s.clearText}>✕</Text>
          </Pressable>
        ) : (
          <Text style={s.triggerCaret}>{open ? '▴' : '▾'}</Text>
        )}
      </Pressable>
      {open && (
        <View style={s.popover}>
          <DayPicker
            mode="single"
            selected={selected}
            onSelect={(d) => {
              if (d) {
                onChange(formatYMD(d));
                setOpen(false);
              }
            }}
            styles={{
              root: {
                margin: 0,
                color: c.text,
                fontFamily: 'Sora_400Regular',
                fontSize: 13,
              },
            }}
            modifiersStyles={{
              selected: { backgroundColor: c.accent, color: c.textOnAccent },
              today: { color: c.accent, fontWeight: '700' },
            }}
          />
        </View>
      )}
    </View>
  );
}

const s = StyleSheet.create({
  trigger: {
    ...t.subtask,
    color: c.text,
    backgroundColor: c.bg,
    borderRadius: r.sm,
    borderWidth: 1,
    borderColor: c.border,
    paddingHorizontal: sp.sm,
    paddingVertical: sp.xs,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: sp.xs,
  },
  triggerText: { ...t.subtask, color: c.text, flex: 1 },
  triggerCaret: { ...t.duration, color: c.textDim },
  clearText: { ...t.taskMeta, color: c.textDim, paddingHorizontal: 2 },
  popover: {
    marginTop: sp.xs,
    backgroundColor: c.surface,
    borderRadius: r.md,
    borderWidth: 1,
    borderColor: c.border,
    padding: sp.xs,
    alignSelf: 'flex-start',
  },
});
