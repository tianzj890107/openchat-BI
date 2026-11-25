import React, {useRef} from "react";

export default function PanelDivider({name, kind, value, min, max, onChange}) {
  const drag = useRef(null);
  const setValue = (next) => onChange(Math.round(Math.max(min, Math.min(max, next))));
  return <div className={`ak-divider ak-divider--${kind}`} role="separator" aria-label={name}
    aria-orientation="vertical" aria-valuemin={min} aria-valuemax={max} aria-valuenow={value} tabIndex={0}
    onPointerDown={(event) => {
      if (event.button !== 0) return;
      drag.current = {x: event.clientX, value, width: event.currentTarget.parentElement.clientWidth};
      event.currentTarget.setPointerCapture(event.pointerId);
    }}
    onPointerMove={(event) => {
      if (!drag.current) return;
      const movement = event.clientX - drag.current.x;
      const available = drag.current.width - (event.currentTarget.parentElement.querySelector(".ak-sessions")?.offsetWidth || 0);
      setValue(drag.current.value + (kind === "sidebar" ? movement : movement / available * 100));
    }}
    onLostPointerCapture={() => { drag.current = null; }}
    onKeyDown={(event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const step = kind === "sidebar" ? 12 : 2;
      setValue(event.key === "Home" ? min : event.key === "End" ? max : value + (event.key === "ArrowLeft" ? -step : step));
    }} />;
}
