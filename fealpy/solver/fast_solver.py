
import numpy as np
from scipy.sparse import coo_matrix, csc_matrix, csr_matrix, block_diag
from scipy.sparse import spdiags, eye, bmat, tril, triu
from scipy.sparse.linalg import cg, inv, dsolve,  gmres, lgmres, LinearOperator, spsolve_triangular
import pyamg

from ..decorator import timer

class IterationCounter(object):
    def __init__(self, disp=True):
        self._disp = disp
        self.niter = 0
    def __call__(self, rk=None):
        self.niter += 1
        if self._disp:
            print('iter %3i\trk = %s' % (self.niter, str(rk)))

class LagrangeFEMFastSolver():
    def __init__(self, A, F, P):
        """


        Notes
        -----
            求解高次拉格朗日有限元的快速算法
        """
        self.A = A
        self.F = F
        self.P = P

class SaddlePointFastSolver():
    def __init__(self, A, F):
        """

        Notes
        -----
            A = (M, B, C), C 可以是 None
            F = (F0, F1), 

            求解如下离散代数系统 
            M   x0 + B x1 = F0 
            B^T x0 + C x1 = F1

        TODO:

        """
        self.A = A
        self.F = F

        M = A[0]
        B = A[1]
        C = A[2]

        self.D = 1.0/M.diagonal() # M 矩阵的对角线的逆
        # S 相当于间断元的刚度矩阵
        S = (B.T@spdiags(self.D, 0, M.shape[0], M.shape[1])@B).tocsr()
        self.ml = pyamg.ruge_stuben_solver(S) # 这里要求必须有网格内部节点 

        # TODO：把间断元插值到连续元线性元空间，然后再做 AMG

    def linear_operator(self, b):
        M = self.A[0]
        B = self.A[1]
        m = M.shape[0]
        n = B.shape[1]
        r = np.zeros_like(b)
        r[:m] = M@b[:m] + B@b[m:]
        r[m:] = B.T@b[:m]
        return r

    def diag_preconditioner(self, b):
        D = self.D
        m = self.A[0].shape[0]
        n = self.A[1].shape[1]

        r = np.zeros_like(b)

        b0 = b[:m]
        b1 = b[m:]

        r[:m] = b0*D
        r[m:] = self.ml.solve(b1, tol=1e-8, accel='cg')       
        return r 
    
    @timer
    def solve(self, tol=1e-8):
        M = self.A[0]
        B = self.A[1]
        C = self.A[2]

        m = M.shape[0]
        n = B.shape[1]
        gdof = m + n

        counter = IterationCounter()
        F = np.r_[self.F[0], self.F[1]]
        A = LinearOperator((gdof, gdof), matvec=self.linear_operator)
        P = LinearOperator((gdof, gdof), matvec=self.diag_preconditioner)
        x, info = lgmres(A, F, M=P, tol=1e-8, callback=counter)
        print("Convergence info:", info)
        print("Number of iteration of gmres:", counter.niter)

        return x[:m], x[m:] 


