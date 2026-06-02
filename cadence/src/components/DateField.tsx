/**
 * Date input that opens a native calendar picker on web (the primary target).
 *
 * On web, renders an HTML <input type="date"> so the user gets the browser's
 * built-in date picker UI (calendar dropdown, keyboard navigation, mobile
 * native picker on touch devices). Output format is YYYY-MM-DD — same as the
 * plain text input it replaces. `colorScheme: dark` tells the browser to
 * style the picker UI with a dark palette so it matches the widget theme.
 *
 * On native (iOS/Android), falls back to a plain numeric text input. Can be
 * upgraded to react-native-modal-datetime-picker when the mobile target ships.
 */

import React from 'react';
import { Platform, StyleProp, TextInput, TextStyle } from 'react-native';

import { widgetColors as c } from '@/src/widget-theme';

interface DateFieldProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  style?: StyleProp<TextStyle>;
}

// RN Web allows raw HTML elements at runtime, but JSX types only know about RN
// components — so we alias 'input' through `any` to satisfy the type checker.
const HtmlInput = 'input' as unknown as React.ComponentType<any>;

export function DateField({
  value, onChange, placeholder = 'YYYY-MM-DD', style,
}: DateFieldProps) {
  if (Platform.OS === 'web') {
    return (
      <HtmlInput
        type="date"
        value={value}
        onChange={(e: any) => onChange(e.target.value)}
        style={{
          fontFamily: 'Sora_400Regular',
          fontSize: 13,
          color: c.text,
          backgroundColor: c.bg,
          borderRadius: 4,
          borderWidth: 1,
          borderStyle: 'solid',
          borderColor: c.border,
          paddingTop: 4,
          paddingBottom: 4,
          paddingLeft: 8,
          paddingRight: 8,
          outlineStyle: 'none',
          colorScheme: 'dark',
          ...((style as object) ?? {}),
        }}
      />
    );
  }
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
