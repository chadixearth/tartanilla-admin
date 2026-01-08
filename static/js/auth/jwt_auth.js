/**
 * JWT Authentication utilities for client-side applications
 * This file provides helper functions for working with Supabase JWT tokens
 */

// Get the Supabase client from the config
const supabase = window.supabaseClient;

/**
 * Login with email and password
 * @param {string} email - User email
 * @param {string} password - User password
 * @returns {Promise} - Promise with login result
 */
async function login(email, password) {
  try {
    const { data, error } = await supabase.auth.signInWithPassword({
      email,
      password,
    });
    
    if (error) throw error;
    
    // Store the JWT token in localStorage
    localStorage.setItem('supabase.auth.token', data.session.access_token);
    
    return {
      success: true,
      user: data.user,
      session: data.session
    };
  } catch (error) {
    console.error('Login error:', error.message);
    return {
      success: false,
      error: error.message
    };
  }
}

/**
 * Logout the current user
 * @returns {Promise} - Promise with logout result
 */
async function logout() {
  try {
    const { error } = await supabase.auth.signOut();
    if (error) throw error;
    
    // Remove the JWT token from localStorage
    localStorage.removeItem('supabase.auth.token');
    
    return { success: true };
  } catch (error) {
    console.error('Logout error:', error.message);
    return {
      success: false,
      error: error.message
    };
  }
}

/**
 * Get the current JWT token
 * @returns {string|null} - The JWT token or null if not logged in
 */
function getToken() {
  return localStorage.getItem('supabase.auth.token');
}

/**
 * Check if the user is authenticated
 * @returns {boolean} - True if the user is authenticated
 */
function isAuthenticated() {
  return !!getToken();
}

/**
 * Get the current user
 * @returns {Promise} - Promise with user data
 */
async function getCurrentUser() {
  try {
    const { data: { user }, error } = await supabase.auth.getUser();
    
    if (error) throw error;
    
    return {
      success: true,
      user
    };
  } catch (error) {
    console.error('Get user error:', error.message);
    return {
      success: false,
      error: error.message
    };
  }
}

/**
 * Verify the current token with the backend
 * @returns {Promise} - Promise with verification result
 */
async function verifyToken() {
  try {
    const token = getToken();
    if (!token) {
      return {
        success: false,
        error: 'No token found'
      };
    }
    
    const response = await fetch('/api/auth/verify-token/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      }
    });
    
    const data = await response.json();
    return data;
  } catch (error) {
    console.error('Token verification error:', error.message);
    return {
      success: false,
      error: error.message
    };
  }
}

/**
 * Add JWT token to fetch requests
 * @param {string} url - The URL to fetch
 * @param {Object} options - Fetch options
 * @returns {Promise} - Promise with fetch result
 */
async function fetchWithAuth(url, options = {}) {
  const token = getToken();
  
  if (!token) {
    throw new Error('No authentication token found');
  }
  
  const headers = {
    ...options.headers,
    'Authorization': `Bearer ${token}`
  };
  
  return fetch(url, {
    ...options,
    headers
  });
}

// Export the functions
window.jwtAuth = {
  login,
  logout,
  getToken,
  isAuthenticated,
  getCurrentUser,
  verifyToken,
  fetchWithAuth
};