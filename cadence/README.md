# cadence/ — mobile app (Expo / React Native)

Bootstrap intentionally deferred to **Phase 5** of the build (Now-screen vertical slice).
`create-expo-app` is heavyweight and not load-bearing for Phases 1–4 (data schema, LLM
decomposition, scheduling engine, calendar MCP). See `../CLAUDE.md` for build order.

When Phase 5 starts, from this directory:

```bash
cd ..   # back to repo root
npx create-expo-app@latest cadence --template default
cd cadence
npx expo install expo-router expo-notifications expo-secure-store
npm install nativewind tailwindcss react-native-reanimated moti
npm install @tanstack/react-query zustand
npx tailwindcss init
```

**Before writing any screens**, read `/mnt/skills/public/frontend-design/SKILL.md` (or
locate it via the `find-skills` skill — it was missing on the dev machine as of
2026-05-16). Translate its web-oriented guidance to React Native + NativeWind: visual
hierarchy, restraint, intentional color, motion with purpose. The Now screen is the
keystone — build it end-to-end first.
