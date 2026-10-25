export default function ErrorState({ title = 'Something went wrong', message = 'Please try again in a moment.' }) {
  return (
    <div className="state-card error-state" role="alert">
      <span className="error-icon" aria-hidden="true">!</span>
      <div>
        <h2>{title}</h2>
        <p>{message}</p>
      </div>
    </div>
  )
}
