import { useEffect, useId, useRef, type ReactNode } from 'react'

/** Native <dialog>: focus is trapped and Esc closes it. Used for revoke/rotate confirmations. */
export function ConfirmDialog({ open, title, children, confirmLabel, danger, busy, confirmDisabled, onConfirm, onCancel }: {
  open: boolean
  title: string
  children: ReactNode
  confirmLabel: string
  danger?: boolean
  busy?: boolean
  confirmDisabled?: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()  // several dialogs can be on one page
  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (open && !d.open) d.showModal()
    if (!open && d.open) d.close()
  }, [open])

  return (
    <dialog ref={ref} className="dialog" aria-labelledby={titleId} onCancel={(e) => { e.preventDefault(); onCancel() }}>
      <h2 id={titleId}>{title}</h2>
      <div className="dialog-body">{children}</div>
      <div className="dialog-actions">
        <button type="button" className="btn btn-secondary" onClick={onCancel} disabled={busy}>ยกเลิก</button>
        <button type="button" className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`} onClick={onConfirm}
          disabled={busy || confirmDisabled} aria-busy={busy}>
          {busy ? 'กำลังดำเนินการ…' : confirmLabel}
        </button>
      </div>
    </dialog>
  )
}
