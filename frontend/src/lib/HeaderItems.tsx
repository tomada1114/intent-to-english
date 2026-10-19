import { createContext, type ReactNode, useContext, useState } from "react";
import { createPortal } from "react-dom";

type SlotSetter = (element: HTMLElement | null) => void;

// undefined: no layout provides a header (a feature rendered on its own);
// null: the layout's slot has not mounted yet.
const SlotContext = createContext<HTMLElement | null | undefined>(undefined);
const SetSlotContext = createContext<SlotSetter | undefined>(undefined);

/** Owns the header slot: wraps both the header and the page that fills it. */
export function HeaderSlotProvider({ children }: { children: ReactNode }) {
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  return (
    <SetSlotContext.Provider value={setSlot}>
      <SlotContext.Provider value={slot}>{children}</SlotContext.Provider>
    </SetSlotContext.Provider>
  );
}

/** Where a page's own header items appear, inside the layout's header. */
export function HeaderSlot({ className }: { className?: string }) {
  const setSlot = useContext(SetSlotContext);
  return <div ref={setSlot} className={className} />;
}

/**
 * A page's own header items, placed in the layout's header without editing the
 * layout. Without a layout (a feature rendered on its own), they render in place.
 */
export function HeaderItems({ children }: { children: ReactNode }) {
  const slot = useContext(SlotContext);
  if (slot === undefined) return <>{children}</>;
  if (slot === null) return null;
  return createPortal(children, slot);
}
