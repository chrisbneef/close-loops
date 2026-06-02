/**
 * Date input. Currently a plain numeric text input (YYYY-MM-DD) on every
 * platform.
 *
 * NOTE: an earlier attempt rendered <input type="date"> on web for the
 * browser's native calendar UI, but React Native Web's renderer doesn't
 * accept raw HTML element strings via JSX — it tried to look up an "input"
 * host component, found nothing, and crashed the entire modal. We'll bring
 * the calendar back with react-native-web's unstable_createElement (or a
 * proper date-picker library) as a follow-up. For now: type-the-date.
 */

import { StyleProp, TextInput, TextStyle } from 'react-native';

import { widgetColors as c } from '@/src/widget-theme';

interface DateFieldProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  style?: StyleProp<TextStyle>;
}

export function DateField({
  value, onChange, placeholder = 'YYYY-MM-DD', style,
}: DateFieldProps) {
  return (
    <TextInput
      value={value}
      onChangeText={onChange}
      placeholder={placeholder}
      placeholderTextColor={c.textFaint}
      inputMode="numeric"
      style={style}
    />
  );
}
