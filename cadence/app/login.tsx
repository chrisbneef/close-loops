/**
 * Login screen — the single entry point to every surface (Now / dashboard /
 * widget). Branded with the dark-slate + lime "Close Your Loops" identity so
 * it reads as the one front door to the desktop product.
 *
 * On success the auth store sets the token; the root layout's Stack.Protected
 * guard flips and routes into the app automatically.
 */

import { useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { useAuth } from '@/src/auth-store';
import {
  widgetColors as c,
  widgetRadii as r,
  widgetSpacing as sp,
  widgetType as t,
} from '@/src/widget-theme';

export default function LoginScreen() {
  const login = useAuth((s) => s.login);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const canSubmit = email.trim().length > 0 && password.length > 0 && !busy;

  const submit = async () => {
    if (!canSubmit) return;
    setError(null);
    setBusy(true);
    try {
      await login(email.trim(), password);
      // Guard in _layout flips to the app automatically.
    } catch (e) {
      const msg = String(e);
      setError(
        msg.includes('401')
          ? 'Incorrect email or password.'
          : msg.includes('503')
            ? 'Auth not configured on the server.'
            : "Can't reach the brain. Is the backend running?",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={s.root}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View style={s.card}>
        <View style={s.brandRow}>
          <View style={s.logoDot} />
          <Text style={s.brand}>CLOSE YOUR LOOPS</Text>
        </View>
        <Text style={s.subtitle}>Sign in to your loops.</Text>

        <Text style={s.label}>EMAIL</Text>
        <TextInput
          value={email}
          onChangeText={setEmail}
          placeholder="you@preapprovemeapp.com"
          placeholderTextColor={c.textFaint}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="email-address"
          textContentType="username"
          style={s.input}
          onSubmitEditing={submit}
        />

        <Text style={s.label}>PASSWORD</Text>
        <TextInput
          value={password}
          onChangeText={setPassword}
          placeholder="••••••••"
          placeholderTextColor={c.textFaint}
          secureTextEntry
          autoCapitalize="none"
          autoCorrect={false}
          textContentType="password"
          style={s.input}
          onSubmitEditing={submit}
          returnKeyType="go"
        />

        {error ? <Text style={s.error}>{error}</Text> : null}

        <Pressable
          onPress={submit}
          disabled={!canSubmit}
          style={({ pressed }) => [
            s.button,
            !canSubmit && s.buttonDisabled,
            pressed && canSubmit && { opacity: 0.85 },
          ]}
        >
          {busy ? (
            <ActivityIndicator color={c.textOnAccent} />
          ) : (
            <Text style={s.buttonText}>SIGN IN</Text>
          )}
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}

const s = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: c.bg,
    alignItems: 'center',
    justifyContent: 'center',
    padding: sp.lg,
  },
  card: {
    width: '100%',
    maxWidth: 360,
    backgroundColor: c.surface,
    borderRadius: r.lg,
    borderWidth: 1,
    borderColor: c.border,
    padding: sp.xl,
    gap: sp.sm,
  },
  brandRow: { flexDirection: 'row', alignItems: 'center', gap: sp.sm },
  logoDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: c.accent },
  brand: { ...t.hud, color: c.text },
  subtitle: { ...t.taskMeta, color: c.textDim, marginBottom: sp.md },
  label: { ...t.micro, color: c.textFaint, marginTop: sp.sm },
  input: {
    ...t.subtask,
    color: c.text,
    backgroundColor: c.bg,
    borderRadius: r.md,
    borderWidth: 1,
    borderColor: c.border,
    paddingHorizontal: sp.md,
    paddingVertical: sp.sm,
    outlineStyle: 'none' as any,
  },
  error: { ...t.taskMeta, color: c.warning, marginTop: sp.sm },
  button: {
    marginTop: sp.lg,
    backgroundColor: c.accent,
    borderRadius: r.md,
    paddingVertical: sp.md,
    alignItems: 'center',
  },
  buttonDisabled: { backgroundColor: c.surfaceElevated },
  buttonText: { ...t.button, color: c.textOnAccent },
});
