/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        spotify: {
          green: '#1DB954',
          'green-dark': '#1aa34a',
          black: '#121212',
          'dark-gray': '#181818',
          'mid-gray': '#282828',
          'light-gray': '#B3B3B3',
        },
      },
    },
  },
  plugins: [],
}
