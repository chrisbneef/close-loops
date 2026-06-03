/**
 * Web DateTimeField — pairs the calendar-picker DateField with a small
 * HH:MM time TextInput. Stores the value as a UTC ISO 8601 string; the
 * displayed date and time are in the user's local timezone.
 *
 * Behavior:
 *   • Picking a new date keeps the existing time.
 *   • Typing a new time keeps the existing date.
 *   • If the date is cleared, the field clears entirely.
 *   • Invalid time strings (e.g. "1:") are held in local UI state without
 *     overwriting the canonical ISO value until they parse cleanly.
 */

import { useEffect, useState } from 'react';
import { StyleProp, StyleSheet, TextInput, TextStyle, View } from 'react-native';

import { DateField } from '@/src/components/DateField';
import {
  widgetColors as c, widgetRadii as r, widgetSpacing as sp, widgetType as t,
} from '@/src/widget-theme';

interface DateTimeFieldProps {
  /** ISO 8601 string in UTC, or empty. */
  value: string;
  /** Receives a new ISO 8601 string in UTC, or empty if cleared. */
  onChange: (iso: string) => void;
  style?: StyleProp<TextStyle>;
}

function isoToLocalDate(iso: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

function isoToLocalTime(iso: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  const hh = String(d.getHours()).padStart(2, '0');
  const mi = String(d.getMinutes()).padStart(2, '0');
  return `${hh}:${mi}`;
}

function combine(dateStr: string, timeStr: string): string {
  if (!dateStr) return '';
  const normalized = /^\d{1,2}:\d{2}$/.test(timeStr)
    ? timeStr.padStart(5, '0')
    : '00:00';
  const local = new Date(`${dateStr}T${normalized}:00`);
  return isNaN(local.getTime()) ? '' : local.toISOString();
}

export function DateTimeField({ value, onChange, style }: DateTimeFieldProps) {
  // Keep the time field as local state so partial typing ("1:") doesn't
  // overwrite the canonical ISO. We re-sync from the prop when it changes
  // (e.g. parent reset).
  const [timeStr, setTimeStr] = useState(isoToLocalTime(value));
  useEffect(() => { setTimeStr(isoToLocalTime(value)); }, [value]);

  const dateStr = isoToLocalDate(value);

  return (
    <View style={s.row}>
      <DateField
        value={dateStr}
        onChange={(d) => onChange(combine(d, timeStr))}
        style={[style as object]}
      />
      <TextInput
        value={timeStr}
        onChangeText={(t) => {
          setTimeStr(t);
          if (/^\d{1,2}:\d{2}$/.test(t)) {
            onChange(combine(dateStr, t));
          }
        }}
        placeholder="HH:MM"
        placeholderTextColor={c.textFaint}
        inputMode="numeric"
        style={s.timeInput}
      />
    </View>
  );
}

const s = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: sp.xs, flexWrap: 'wrap' },
  timeInput: {
    ...t.subtask,
    color: c.text,
    backgroundColor: c.bg,
    borderRadius: r.sm,
    borderWidth: 1,
    borderColor: c.border,
    paddingHorizontal: sp.sm,
    paddingVertical: sp.xs,
    outlineStyle: 'none' as any,
    width: 80,
    textAlign: 'center',
  },
});
