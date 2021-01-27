import numpy as np
import tensorly as tl
import time
from tensorly.tenalg import inner
from numpy.linalg import norm
from numpy.linalg import svd

'''
Takes two vectors, x (the user vectors) and y (the observed feature vectors)
and returns a covariate tensor cov_X in R^{d1 x d2 x T}.

Input: x in R^{d1}, y in R^{d2}, t (int), T (number of tasks)
Output: cov_X in R^{d1 x d2 x T}
'''
def generate_covariate_X(x, y, t, T):
    outer = np.outer(x, y)
    cov_X = np.zeros((len(x), len(y), T)) # d1 x d2 x T
    cov_X[:, :, t] = outer
    return cov_X

'''
Takes a tensor B, and computes the Schatten-1 Norm of B 
(average of the nuclear norms of its modes).

Input: B (d1 x d2 x T tensor)
Output: ||B||_S (float)
'''
def schatten1_norm(B):
    total_norm = 0
    for mode in range(B.ndim):
        total_norm += norm(tl.unfold(B, mode), 'nuc')

    total_norm = (1/B.ndim) * total_norm
    return total_norm

'''
Takes a response matrix R (N x T), a list of covariate X (N of them),
and the current iteration's B and outputs the value of the objective function:

    (1/N) sum_{i = 1}^N (R_{i, t(i)} - <X_i, B>)^2 + \lambd ||B||_S

where ||B||_S is the Schatten-1 Norm of B.

Input: R (N x T matrix), cov_X_list (list of N d1xd2xT tensors), B (d1 x d2 x T tensor), lambd (float)
Output: Objective function value (float)
'''
def objective(R_indexed, cov_X, B, inner_X_B, lambd, task_function, batch):
    # The inner products have already been precalculated in inner_X_B
    cost = np.sum(np.square(R_indexed - inner_X_B))

    # Unoptimized for loop (DEPRECATED)
    #cost = 0
    #for i in batch:
    #    cost += (R[i][task_function[i]] - inner(B, cov_X_list[i])) ** 2 # tensor inner product

    cost = float(1/len(batch)) * cost # 1/N sum [(R_i - <X_i, B>)^2]

    # Regularizer
    cost += lambd * schatten1_norm(B)
    return cost

'''
Takes a response matrix R (N x T), a list of covariate X (N of them),
and the current iteration's B and outputs the gradient tensor in d1 x d2 x T:
    
    (2/N) sum_{i = 1}^N (R_{i, t(i)} - <X_i, B>) -X_i + (\lambd/3) * (D_(1) + D_(2) + D_(3))

where that last term is achieved by 3 SVD's, one on each mode of B, and D_(i) = U_(i)V_(i)^T in the SVD.

Input: R (N x T matrix), cov_X_list (list of N d1xd2xT tensors), B (d1 x d2 x T tensor), lambd (float)
Output: Gradient Tensor (d1 x d2 x T)
'''
def gradient(R_indexed, cov_X, B, inner_X_B, lambd, task_function, batch):
    # New and improved  
    gradient = np.zeros(B.shape)
    cost = R_indexed - inner_X_B
    summand = cost.reshape((-1,) + (1,)*(cov_X.ndim - 1)) * (-1 * cov_X)
    for i in batch:
        gradient[:, :, task_function[i]] += summand[i]

    # Main sum
    #gradient = np.zeros(B.shape) # d1 x d2 x T
    #for i in batch: # full gradient (over all N users)
    #    gradient += (R[i][task_function[i]] - inner(cov_X_list[i], B)) * (-1 * cov_X_list[i])

    gradient = float(2/len(batch)) * gradient

    # Gradient of Regularizer
    original_shape = B.shape
    avg_reg = np.zeros(original_shape)
    for mode in range(B.ndim):
        unfolded_B = tl.unfold(B, mode) # matrix
        U, _, V_T = svd(unfolded_B, full_matrices=False)
        D_mode = np.matmul(U, V_T)
        folded_D = tl.fold(D_mode, mode, original_shape)
        avg_reg += folded_D
    reg_term = avg_reg/float(B.ndim) * lambd # avg. over the three unfoldings

    # Gradient is sum of gradient and reg_term
    final_grad = gradient + reg_term
    return final_grad

def batch_grad_descent(true_B, A, R, X, Y, cov_X, T, eta, eps, lambd, task_function, iterations=200):
    # Initialize B to a random tensor d1 x d2 x T
    B = np.random.randn(X.shape[1], Y.shape[1], T)
    error_list = []
    batch = list(range(len(R)))
    # B = np.zeros((X.shape[1], Y.shape[1], T))

    # Main gradient descent loop
    past_objective = 0
    prev_obj_delta = 0
    for iteration in range(iterations):
        # start = time.time()
        
        # Precalculate indexing R by task function and the inner products <X_i, B>
        R_indexed = R[np.arange(len(R)), task_function]
        inner_X_B = calculate_inner_X_B(cov_X, B, task_function)

        # Calculate cost
        curr_objective = objective(R_indexed, cov_X, B, inner_X_B, lambd, task_function, batch)
        true_objective = objective(R_indexed, cov_X, true_B, inner_X_B, lambd, task_function, batch)

        # Stopping condition 
        current_obj_delta = np.abs(past_objective - curr_objective)
        stopping_condition = 1e10              # Don't stop 
        if(stopping_condition < eps):
            return B
        past_objective = curr_objective
        prev_obj_delta = current_obj_delta
        if (iteration + 1) % 10 == 0:
            print("Cost on iteration {}: {}".format(iteration + 1, curr_objective))
        if (iteration + 1) % 10 == 0:
            print("Cost on iteration {}: {}".format(iteration + 1, true_objective))
        
        error_list.append(curr_objective)

        # Calculate gradient
        # Full batch gradient descent
        grad = gradient(R_indexed, cov_X, B, inner_X_B, lambd, task_function, batch)
        
        # Cut down eta
        if (iteration + 1) % 25 == 0:
            eta = eta/2
        
        # Update B
        B = B - eta * grad
        
        # end = time.time()
        # print("Time per iteration: {}".format(end - start))

    return B

# Calculates the inner product of each X_i and B
def calculate_inner_X_B(cov_X, B, task_function):
    B_indexed = np.moveaxis(B[:, :, task_function], -1, 0)
    inner_X_B = np.multiply(cov_X, B_indexed)
    inner_X_B_summed = inner_X_B.reshape(inner_X_B.shape[0],-1).sum(axis=1)
    return inner_X_B_summed

'''
def grad_descent(A, R, X, Y, cov_X_list, T, eta, eps, lambd, task_function, batch_size=32, iterations=20):
    # Initialize B to a random tensor d1 x d2 x T
    B = np.random.randn(X.shape[1], Y.shape[1], T)
    error_list = []
    # B = np.zeros((X.shape[1], Y.shape[1], T))

    # Main gradient descent loop
    for iteration in range(iterations):
        # Mini-batch gradient descent
        batched_examples = list(create_mini_batches(len(R), batch_size))
        for batch in batched_examples:
            grad = gradient(R, cov_X_list, B, lambd, task_function, batch)
            B = B - eta * grad
            cost = objective(R, cov_X_list, B, lambd, task_function, batch)
            print("Cost on iteration {}: {}".format(iteration + 1, cost))
            error_list.append(cost)

    return B, error_list

def create_mini_batches(num_examples, batch_size):
    examples = list(range(num_examples))
    np.random.shuffle(examples)
    for i in range(0, len(examples), batch_size):
        yield examples[i:i + batch_size]
'''