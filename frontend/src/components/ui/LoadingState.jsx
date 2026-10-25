export default function LoadingState({ label = 'Loading' }) {
  return (
    <div className="state-card" role="status" aria-live="polite">
      <span className="loading-dot" aria-hidden="true" />
      <span>{label}</span>
    </div>
  )
}
