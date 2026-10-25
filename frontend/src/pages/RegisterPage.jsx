import { Link } from 'react-router-dom'

export default function RegisterPage() {
  return (
    <section className="page-panel narrow-panel">
      <p className="eyebrow">A PLACE FOR THE GOOD STUFF</p>
      <h1>Make yourself<br /><em>at home.</em></h1>
      <p className="page-description">Registration will be available in a later phase.</p>
      <div className="placeholder-notice" role="status">Your Nexora account is just around the corner.</div>
      <p className="form-footnote">Already have an account? <Link to="/login">Sign in</Link></p>
    </section>
  )
}
