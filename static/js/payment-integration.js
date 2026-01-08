/**
 * PayMongo Payment Integration for Tourism Booking System
 * This script handles the complete booking and payment flow
 */

class TourismPaymentSystem {
    constructor(apiBaseUrl = '/api') {
        this.apiBaseUrl = apiBaseUrl;
        this.currentBookingId = null;
        this.currentPaymentId = null;
    }

    /**
     * Create a new booking
     */
    async createBooking(bookingData) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/tour-booking/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify(bookingData)
            });

            const result = await response.json();

            if (result.success) {
                this.currentBookingId = result.booking_id;
                console.log('Booking created successfully:', result);
                
                if (result.payment_required) {
                    return {
                        success: true,
                        booking: result.data,
                        requiresPayment: true,
                        message: result.message
                    };
                }
            } else {
                throw new Error(result.error || 'Failed to create booking');
            }

            return result;
        } catch (error) {
            console.error('Error creating booking:', error);
            throw error;
        }
    }

    /**
     * Create payment for a booking
     */
    async createPayment(bookingId, paymentMethodType = 'gcash') {
        try {
            const response = await fetch(`${this.apiBaseUrl}/payments/create-payment/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({
                    booking_id: bookingId,
                    payment_method_type: paymentMethodType
                })
            });

            const result = await response.json();

            if (result.success) {
                this.currentPaymentId = result.data.payment_id;
                console.log('Payment intent created:', result);
                return result;
            } else {
                throw new Error(result.error || 'Failed to create payment');
            }
        } catch (error) {
            console.error('Error creating payment:', error);
            throw error;
        }
    }

    /**
     * Process payment using PayMongo
     */
    async processPayment(paymentData, customerDetails) {
        try {
            // For GCash, Maya, or GrabPay - redirect to payment page
            if (['gcash', 'paymaya', 'grab_pay'].includes(paymentData.payment_method_type)) {
                return this.processEWalletPayment(paymentData, customerDetails);
            }
            
            // For card payments - use PayMongo.js
            if (paymentData.payment_method_type === 'card') {
                return this.processCardPayment(paymentData, customerDetails);
            }

            throw new Error('Unsupported payment method');
        } catch (error) {
            console.error('Error processing payment:', error);
            throw error;
        }
    }

    /**
     * Process e-wallet payments (GCash, Maya, GrabPay)
     */
    async processEWalletPayment(paymentData, customerDetails) {
        try {
            // Create payment method
            const paymentMethod = await this.createPaymentMethod({
                type: paymentData.payment_method_type,
                details: {
                    // E-wallet payments don't need additional details
                }
            });

            // Attach payment method to payment intent
            const attachResult = await this.attachPaymentMethod(
                paymentData.payment_intent_id, 
                paymentMethod.id
            );

            if (attachResult.next_action && attachResult.next_action.redirect) {
                // Redirect user to payment page
                window.location.href = attachResult.next_action.redirect.url;
                return { success: true, redirected: true };
            }

            return attachResult;
        } catch (error) {
            console.error('Error processing e-wallet payment:', error);
            throw error;
        }
    }

    /**
     * Process card payments
     */
    async processCardPayment(paymentData, customerDetails) {
        try {
            // This would integrate with PayMongo.js for card payments
            // For now, return a placeholder
            console.log('Card payment processing would be implemented here');
            
            return {
                success: false,
                error: 'Card payment integration requires PayMongo.js SDK'
            };
        } catch (error) {
            console.error('Error processing card payment:', error);
            throw error;
        }
    }

    /**
     * Confirm payment after user returns from payment page
     */
    async confirmPayment(paymentIntentId) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/payments/confirm-payment/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({
                    payment_intent_id: paymentIntentId
                })
            });

            const result = await response.json();
            console.log('Payment confirmation result:', result);
            return result;
        } catch (error) {
            console.error('Error confirming payment:', error);
            throw error;
        }
    }

    /**
     * Get payment status
     */
    async getPaymentStatus(paymentId) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/payments/status/${paymentId}/`);
            const result = await response.json();
            return result;
        } catch (error) {
            console.error('Error getting payment status:', error);
            throw error;
        }
    }

    /**
     * Complete booking flow: Create booking -> Create payment -> Process payment
     */
    async completeBookingWithPayment(bookingData, paymentMethodType = 'gcash') {
        try {
            // Step 1: Create booking
            console.log('Step 1: Creating booking...');
            const bookingResult = await this.createBooking(bookingData);
            
            if (!bookingResult.success) {
                throw new Error('Failed to create booking');
            }

            const bookingId = bookingResult.booking.id;
            console.log('Booking created with ID:', bookingId);

            // Step 2: Create payment
            console.log('Step 2: Creating payment...');
            const paymentResult = await this.createPayment(bookingId, paymentMethodType);
            
            if (!paymentResult.success) {
                throw new Error('Failed to create payment');
            }

            console.log('Payment created:', paymentResult);

            // Step 3: Process payment
            console.log('Step 3: Processing payment...');
            const processResult = await this.processPayment({
                payment_intent_id: paymentResult.data.payment_intent_id,
                payment_method_type: paymentMethodType
            }, bookingData);

            return {
                success: true,
                booking: bookingResult.booking,
                payment: paymentResult.data,
                processResult: processResult
            };

        } catch (error) {
            console.error('Error in complete booking flow:', error);
            return {
                success: false,
                error: error.message
            };
        }
    }

    /**
     * Handle return from payment page
     */
    async handlePaymentReturn(paymentIntentId) {
        try {
            console.log('Handling payment return for:', paymentIntentId);
            
            const confirmResult = await this.confirmPayment(paymentIntentId);
            
            if (confirmResult.success) {
                if (confirmResult.data.payment_status === 'succeeded') {
                    this.showSuccessMessage(confirmResult.message);
                    return { success: true, status: 'succeeded' };
                } else if (confirmResult.data.payment_status === 'failed') {
                    this.showErrorMessage(confirmResult.message);
                    return { success: false, status: 'failed' };
                } else {
                    this.showInfoMessage(confirmResult.message);
                    return { success: true, status: 'processing' };
                }
            } else {
                this.showErrorMessage(confirmResult.error);
                return { success: false, error: confirmResult.error };
            }
        } catch (error) {
            console.error('Error handling payment return:', error);
            this.showErrorMessage('Error processing payment confirmation');
            return { success: false, error: error.message };
        }
    }

    /**
     * Utility: Get CSRF token
     */
    getCSRFToken() {
        const cookies = document.cookie.split(';');
        for (let cookie of cookies) {
            const [name, value] = cookie.trim().split('=');
            if (name === 'csrftoken') {
                return value;
            }
        }
        return '';
    }

    /**
     * UI Helper: Show success message
     */
    showSuccessMessage(message) {
        console.log('SUCCESS:', message);
        // Implement your UI notification system here
        alert('Success: ' + message);
    }

    /**
     * UI Helper: Show error message
     */
    showErrorMessage(message) {
        console.error('ERROR:', message);
        // Implement your UI notification system here
        alert('Error: ' + message);
    }

    /**
     * UI Helper: Show info message
     */
    showInfoMessage(message) {
        console.log('INFO:', message);
        // Implement your UI notification system here
        alert('Info: ' + message);
    }
}

// Usage Example:
/*
const paymentSystem = new TourismPaymentSystem();

// Example booking data
const bookingData = {
    package_id: 'your-package-id',
    customer_id: 'your-customer-id',
    booking_date: '2024-02-15',
    pickup_time: '09:00:00',
    number_of_pax: 2,
    contact_number: '+639123456789',
    pickup_address: 'Plaza Independencia, Cebu City',
    special_requests: 'Please pick up early'
};

// Complete booking with GCash payment
paymentSystem.completeBookingWithPayment(bookingData, 'gcash')
    .then(result => {
        if (result.success) {
            console.log('Booking and payment initiated successfully!');
            // User will be redirected to payment page
        } else {
            console.error('Failed to complete booking:', result.error);
        }
    });

// Handle return from payment page (put this on your return URL page)
const urlParams = new URLSearchParams(window.location.search);
const paymentIntentId = urlParams.get('payment_intent_id');

if (paymentIntentId) {
    paymentSystem.handlePaymentReturn(paymentIntentId)
        .then(result => {
            if (result.success && result.status === 'succeeded') {
                console.log('Payment successful! Booking confirmed.');
                // Redirect to booking confirmation page
            }
        });
}
*/

// Export for use in other scripts
if (typeof module !== 'undefined' && module.exports) {
    module.exports = TourismPaymentSystem;
} else if (typeof window !== 'undefined') {
    window.TourismPaymentSystem = TourismPaymentSystem;
}