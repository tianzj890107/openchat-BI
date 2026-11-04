import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const source = (name) => readFileSync(join(here, "..", "src", name), "utf8");

test("model settings are declared in React instead of mirrored from hidden controls", () => {
  const settings = source("ProUiSettingsPage.jsx");
  assert.match(settings, /<Form/);
  assert.doesNotMatch(settings, /settings-model/);
  assert.doesNotMatch(settings, /setInterval\s*\(/);
});

test("composer state is event-driven rather than polled from the legacy input", () => {
  const composer = source("ProUiComposer.jsx");
  assert.doesNotMatch(composer, /setInterval\s*\(/);
  assert.doesNotMatch(composer, /320/);
  assert.match(composer, /bi-composer-state/);
});

test("page control bridge has no timer polling and disposes every React root", () => {
  const controls = source("ProUiPageControls.jsx");
  assert.doesNotMatch(controls, /setInterval\s*\(/);
  assert.match(controls, /\.unmount\(\)/);
  assert.match(controls, /visibilityObserver\.disconnect\(\)/);
});
