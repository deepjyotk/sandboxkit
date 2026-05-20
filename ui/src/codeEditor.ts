/** Thin wrapper around CodeMirror 6 so playground code stays decoupled from the editor lib. */

import { basicSetup, EditorView } from "codemirror";
import { Compartment, EditorState } from "@codemirror/state";
import { python } from "@codemirror/lang-python";
import { javascript } from "@codemirror/lang-javascript";

import type { Lang } from "./constants";

export type EditorHandle = {
  getValue: () => string;
  setValue: (v: string) => void;
  setLanguage: (l: Lang) => void;
  destroy: () => void;
};

const langCompartment = new Compartment();

function langExt(l: Lang) {
  return l === "python" ? python() : javascript();
}

export function createEditor(parent: HTMLElement, doc: string, lang: Lang): EditorHandle {
  const state = EditorState.create({
    doc,
    extensions: [basicSetup, langCompartment.of(langExt(lang))],
  });
  const view = new EditorView({ state, parent });
  return {
    getValue: () => view.state.doc.toString(),
    setValue: (v) =>
      view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: v } }),
    setLanguage: (l) =>
      view.dispatch({ effects: langCompartment.reconfigure(langExt(l)) }),
    destroy: () => view.destroy(),
  };
}
