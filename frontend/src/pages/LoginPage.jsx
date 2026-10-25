import { Link } from 'react-router-dom'

export default function LoginPage() {
  return (
    <section className="page-panel narrow-panel">
      <p className="eyebrow">WELCOME BACK</p>
      <h1>Good to see<br /><em>you again.</em></h1>
      <p className="page-description">Sign-in will be available in a later phase.</p>
      <div className="placeholder-notice" role="status">Your account space is being prepared.</div>
      <p className="form-footnote">New to Nexora? <Link to="/register">Create an account</Link></p>
    </section>
  )
}
