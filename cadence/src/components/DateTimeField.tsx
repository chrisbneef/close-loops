/**
 * Native fallback for DateTimeField — plain text input that accepts
 * `YYYY-MM-DD HH:MM`. Metro picks DateTimeField.web.tsx for web bundles
 * which uses the calendar picker; this file ships only to native.
 */

import { StyleProp, TextInput, TextStyle } from 'react-native';

import { widgetColors as c } from '@/src/widget-theme';

interface DateTimeFieldProps {
  /** ISO 8601 string in UTC, or empty. */
  value: string;
  /** Receives a new ISO 8601 string in UTC, or empty if cleared. */
  onChange: (iso: string) => void;
  style?: StyleProp<TextStyle>;
}

function isoToLocal(iso: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  const hh = String(d.getHours()).padStart(2, '0');
  const mi = String(d.getMinutes()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}`;
}

export function DateTimeField({ value, onChange, style }: DateTimeFieldProps) {
  return (
    <TextInput
      value={isoToLocal(value)}
      onChangeText={(text) => {
        const m = text.match(/^(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})$/);
        if (!m) return;
        const local = new Date(`${m[1]}T${m[2].padStart(2, '0')}:${m[3]}:00`);
        if (isNaN(local.getTime())) return;
        onChange(local.toISOString());
      }}
      placeholder="YYYY-MM-DD HH:MM"
      placeholderTextColor={c.textFaint}
      inputMode="numeric"
      style={style}
    />
  );
}
