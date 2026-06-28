/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        mono: ['"Fira Code"', 'ui-monospace', 'monospace'],
        sans: ['"Fira Code"', 'ui-monospace', 'monospace'],
      },
      colors: {
        aeon: {
          primary:  '#e06c75',   // Odysseus red
          dark:     '#282c34',   // Odysseus bg
          surface:  '#21252b',   // panel
          border:   '#355a66',   // teal border
          cyan:     '#9cdef2',   // Odysseus fg
          green:    '#50fa7b',
          warn:     '#f0ad4e',
        },
        // Remap the indigo scale → Odysseus red/cyan so all existing
        // bg-indigo-*/text-indigo-*/border-indigo-* classes shift automatically
        indigo: {
          300:  '#b8e8f5',
          400:  '#9cdef2',   // cyan — text accents
          500:  '#e06c75',   // red  — primary accent
          600:  '#c25b63',   // darker red — buttons
          700:  '#9e4850',
          800:  '#2a1c1f',
          950:  '#1a2830',   // teal-dark — section backgrounds
        },
      }
    }
  },
  plugins: []
}
