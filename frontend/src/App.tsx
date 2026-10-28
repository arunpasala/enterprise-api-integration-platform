import { useEffect, useState, type FormEvent } from 'react'
import './App.css'

interface Integration {
  id: number
  customer_id: number
  status: string
  attempts: number
  last_error: string | null
}

interface Metrics {
  pending?: number
  retrying?: number
  delivered?: number
  failed?: number
}

interface Customer {
  id: number
  name: string
  email: string
  sync_status: string
}

const API_KEY = import.meta.env.VITE_API_KEY ?? ''

function App() {
  const [integrations, setIntegrations] = useState<Integration[]>([])
  const [metrics, setMetrics] = useState<Metrics>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [retryingId, setRetryingId] = useState<number | null>(null)

  // Customer form state
  const [customerName, setCustomerName] = useState('')
  const [customerEmail, setCustomerEmail] = useState('')
  const [creatingCustomer, setCreatingCustomer] = useState(false)
  const [customerMessage, setCustomerMessage] = useState('')

  // Keep the same idempotency key when retrying an uncertain submission.
  const [submissionKey, setSubmissionKey] = useState(() =>
    crypto.randomUUID()
  )

  async function loadDashboard() {
    try {
      const headers = {
        'X-API-Key': API_KEY,
      }

      const [integrationsResponse, metricsResponse] = await Promise.all([
        fetch('/api/integrations', { headers }),
        fetch('/api/metrics', { headers }),
      ])

      if (!integrationsResponse.ok || !metricsResponse.ok) {
        throw new Error('Unable to load integration data')
      }

      const integrationData: Integration[] =
        await integrationsResponse.json()

      const metricsData: Metrics =
        await metricsResponse.json()

      setIntegrations(integrationData)
      setMetrics(metricsData)
      setError('')
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'Unable to load dashboard'
      )
    } finally {
      setLoading(false)
    }
  }

  // Automatically refresh every five seconds
useEffect(() => {
  const controller = new AbortController()

  async function fetchInitialDashboard() {
    try {
      const headers = {
        'X-API-Key': API_KEY,
      }

      const [integrationsResponse, metricsResponse] = await Promise.all([
        fetch('/api/integrations', {
          headers,
          signal: controller.signal,
        }),
        fetch('/api/metrics', {
          headers,
          signal: controller.signal,
        }),
      ])

      if (!integrationsResponse.ok || !metricsResponse.ok) {
        throw new Error('Unable to load integration data')
      }

      const integrationData: Integration[] =
        await integrationsResponse.json()

      const metricsData: Metrics =
        await metricsResponse.json()

      if (!controller.signal.aborted) {
        setIntegrations(integrationData)
        setMetrics(metricsData)
        setError('')
      }
    } catch (err) {
      if (!controller.signal.aborted) {
        setError(
          err instanceof Error
            ? err.message
            : 'Unable to load dashboard'
        )
      }
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false)
      }
    }
  }

  void fetchInitialDashboard()

  const interval = setInterval(() => {
    void loadDashboard()
  }, 5000)

  return () => {
    controller.abort()
    clearInterval(interval)
  }
}, [])

  // Create customer through FastAPI
  async function handleCreateCustomer(
    event: FormEvent<HTMLFormElement>
  ) {
    event.preventDefault()

    const name = customerName.trim()
    const email = customerEmail.trim()

    if (!name || !email) {
      setError('Please enter a customer name and email address.')
      return
    }

    setCreatingCustomer(true)
    setCustomerMessage('')
    setError('')

    try {
      const response = await fetch('/api/customers', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': API_KEY,
          'Idempotency-Key': submissionKey,
        },
        body: JSON.stringify({
          name,
          email,
        }),
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => null)

        throw new Error(
          typeof errorData?.detail === 'string'
            ? errorData.detail
            : `Customer creation failed: HTTP ${response.status}`
        )
      }

      const customer: Customer = await response.json()

      setCustomerMessage(
        `Customer "${customer.name}" created successfully! Customer ID: ${customer.id}. Synchronization status: ${customer.sync_status}.`
      )

      setCustomerName('')
      setCustomerEmail('')
      setSubmissionKey(crypto.randomUUID())

      await loadDashboard()
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'Failed to create customer'
      )
    } finally {
      setCreatingCustomer(false)
    }
  }

  // Retry failed integration
  async function handleRetry(customerId: number) {
    setRetryingId(customerId)
    setError('')

    try {
      const response = await fetch(
        `/api/integrations/${customerId}/retry`,
        {
          method: 'POST',
          headers: {
            'X-API-Key': API_KEY,
          },
        }
      )

      if (!response.ok) {
        throw new Error(
          `Retry failed: HTTP ${response.status}`
        )
      }

      await loadDashboard()
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'Unable to retry integration'
      )
    } finally {
      setRetryingId(null)
    }
  }

  const total =
    (metrics.delivered ?? 0) +
    (metrics.failed ?? 0) +
    (metrics.pending ?? 0) +
    (metrics.retrying ?? 0)

  return (
    <div className="dashboard">

      {/* Header */}
      <header className="header">
        <div>
          <h1>Enterprise API Integration Platform</h1>
          <p>Integration Monitoring Dashboard</p>
        </div>

        <div className="live-status">
          <span className="live-dot"></span>
          Auto-refresh: 5 seconds
        </div>
      </header>

      {/* Metrics */}
      <div className="stats-grid">
        <div className="stat-card">
          <span>Total Integrations</span>
          <h2>{total}</h2>
        </div>

        <div className="stat-card">
          <span>Delivered</span>
          <h2 className="green">
            {metrics.delivered ?? 0}
          </h2>
        </div>

        <div className="stat-card">
          <span>Pending / Retrying</span>
          <h2 className="orange">
            {(metrics.pending ?? 0) + (metrics.retrying ?? 0)}
          </h2>
        </div>

        <div className="stat-card">
          <span>Failed</span>
          <h2 className="red">
            {metrics.failed ?? 0}
          </h2>
        </div>
      </div>

      {/* Add New Customer */}
      <section className="customer-section">
        <div className="section-header">
          <div>
            <h2>Add New Customer</h2>
            <p>
              Create a customer and automatically initiate
              partner API synchronization.
            </p>
          </div>
        </div>

        <form
          className="customer-form"
          onSubmit={handleCreateCustomer}
        >
          <div className="form-group">
            <label htmlFor="customerName">
              Customer Name
            </label>

            <input
              id="customerName"
              type="text"
              placeholder="Enter customer name"
              value={customerName}
              onChange={(event) => {
                setCustomerName(event.target.value)
                setSubmissionKey(crypto.randomUUID())
              }}
              minLength={1}
              maxLength={200}
              required
            />
          </div>

          <div className="form-group">
            <label htmlFor="customerEmail">
              Email Address
            </label>

            <input
              id="customerEmail"
              type="email"
              placeholder="Enter email address"
              value={customerEmail}
              onChange={(event) => {
                setCustomerEmail(event.target.value)
                setSubmissionKey(crypto.randomUUID())
              }}
              maxLength={320}
              required
            />
          </div>

          <button
            type="submit"
            className="create-btn"
            disabled={creatingCustomer}
          >
            {creatingCustomer
              ? 'Creating...'
              : '+ Create Customer'}
          </button>
        </form>

        {customerMessage && (
          <div className="success-banner" role="status">
            {customerMessage}
          </div>
        )}
      </section>

      {/* Integration Jobs */}
      <section className="integrations-section">
        <div className="section-header">
          <h2>Integration Jobs</h2>

          <button
            type="button"
            onClick={() => void loadDashboard()}
          >
            Refresh
          </button>
        </div>

        {error && (
          <div className="error-banner" role="alert">
            {error}
          </div>
        )}

        {loading ? (
          <p>Loading integrations...</p>
        ) : (
          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>Integration ID</th>
                  <th>Customer ID</th>
                  <th>Status</th>
                  <th>Attempts</th>
                  <th>Last Error</th>
                  <th>Action</th>
                </tr>
              </thead>

              <tbody>
                {integrations.map((integration) => (
                  <tr key={integration.id}>
                    <td>#{integration.id}</td>

                    <td>
                      {integration.customer_id}
                    </td>

                    <td>
                      <span
                        className={`badge ${integration.status}`}
                      >
                        {integration.status}
                      </span>
                    </td>

                    <td>
                      {integration.attempts}
                    </td>

                    <td className="error-text">
                      {integration.last_error || '—'}
                    </td>

                    <td>
                      {integration.status === 'failed' ? (
                        <button
                          type="button"
                          className="retry-btn"
                          disabled={
                            retryingId === integration.customer_id
                          }
                          onClick={() =>
                            void handleRetry(
                              integration.customer_id
                            )
                          }
                        >
                          {retryingId === integration.customer_id
                            ? 'Retrying...'
                            : 'Retry'}
                        </button>
                      ) : (
                        '—'
                      )}
                    </td>
                  </tr>
                ))}

                {integrations.length === 0 && (
                  <tr>
                    <td colSpan={6}>
                      No integration jobs found.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Footer */}
      <footer>
        Enterprise Integration Platform | React + FastAPI + PostgreSQL
      </footer>
    </div>
  )
}

export default App