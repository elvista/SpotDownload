import React from 'react';

/**
 * Catches React render errors and shows a fallback UI instead of a blank screen.
 */
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-spotify-black flex items-center justify-center p-6">
          <div className="max-w-md w-full p-8 bg-spotify-dark-gray rounded-2xl border border-white/10 text-center">
            <h2 className="text-xl font-semibold text-white mb-2">Something went wrong</h2>
            <p className="text-spotify-light-gray text-sm mb-4">
              The app encountered an error. Try refreshing the page.
            </p>
            {this.state.error && (
              <p className="text-xs text-red-400/80 mb-4 font-mono break-all">
                {this.state.error.message}
              </p>
            )}
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="px-5 py-2.5 bg-spotify-green hover:bg-spotify-green-dark text-black font-semibold rounded-xl"
            >
              Reload page
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
