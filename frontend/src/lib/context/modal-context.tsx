"use client";

import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";

type ModalType = "create-task" | null;

interface ModalContextValue {
  modal: ModalType;
  openCreateTask: (agentId?: string, projectId?: string) => void;
  closeModal: () => void;
  presetAgentId: string;
  presetProjectId: string;
}

const ModalContext = createContext<ModalContextValue | null>(null);

export function ModalProvider({ children }: { children: ReactNode }) {
  const [modal, setModal] = useState<ModalType>(null);
  const [presetAgentId, setPresetAgentId] = useState("");
  const [presetProjectId, setPresetProjectId] = useState("");

  const openCreateTask = useCallback((agentId = "", projectId = "") => {
    setPresetAgentId(agentId);
    setPresetProjectId(projectId);
    setModal("create-task");
  }, []);

  const closeModal = useCallback(() => {
    setModal(null);
    setPresetAgentId("");
    setPresetProjectId("");
  }, []);

  return (
    <ModalContext.Provider
      value={{ modal, openCreateTask, closeModal, presetAgentId, presetProjectId }}
    >
      {children}
    </ModalContext.Provider>
  );
}

export function useModal() {
  const ctx = useContext(ModalContext);
  if (!ctx) throw new Error("useModal must be used within ModalProvider");
  return ctx;
}
