// Initialize the Supabase client
const supabaseUrl = 'https://sncruycikvfnkrmmbjxr.supabase.co';
const supabaseAnonKey = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNuY3J1eWNpa3ZmbmtybW1ianhyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTEwMTQ1NDIsImV4cCI6MjA2NjU5MDU0Mn0.NOJVi5idcC3hIZVl5W6Spjs-DBH0_mDINc0Jr0H5v7s';

// Make Supabase client available globally
window.supabase = supabase.createClient(supabaseUrl, supabaseAnonKey);