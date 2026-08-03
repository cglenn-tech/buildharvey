'use client'

export default function PrintButton({ label = 'Print / Save as PDF' }: { label?: string }) {
  return (
    <button
      onClick={() => window.print()}
      className="text-sm text-neutral-500 underline hover:text-neutral-900 transition-colors"
    >
      {label}
    </button>
  )
}
