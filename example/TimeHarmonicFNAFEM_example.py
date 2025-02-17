#!/usr/bin/env python3
# 
import sys
import argparse

import numpy as np
from numpy.linalg import inv
from scipy.sparse import spdiags
from scipy.sparse.linalg import spsolve
import matplotlib.pyplot as plt

from fealpy.mesh import MeshFactory
from fealpy.pde.timeharmonic_2d import CosSinData, LShapeRSinData, InHomogeneousData
from fealpy.functionspace import FirstKindNedelecFiniteElementSpace2d 
from fealpy.functionspace import LagrangeFiniteElementSpace
from fealpy.boundarycondition import DirichletBC 

from fealpy.mesh.adaptive_tools import mark
from fealpy.tools.show import showmultirate
from fealpy.tools.show import show_error_table


def curl_recover(uh):

    mesh = uh.space.mesh
    space = LagrangeFiniteElementSpace(mesh, p=1)
    ruh = space.function() # (gdof, 2)

    bc = np.array([1/3, 1/3, 1/3], dtype=mesh.ftype)
    val = uh.curl_value(bc) #(NC, )
    w = 1/mesh.entity_measure('cell')
    val *= w

    NN = mesh.number_of_nodes() 
    NC = mesh.number_of_cells()
    cell = mesh.entity('cell')
    w = np.broadcast_to(w.reshape(-1, 1), shape=cell.shape)
    W = np.zeros(NN, dtype=mesh.ftype)
    np.add.at(W, cell, w)

    val = np.broadcast_to(val.reshape(-1, 1), shape=cell.shape)
    np.add.at(ruh, cell, val)
    ruh /= W

    return ruh

def spr_edge(mesh, h, edgeVal):

    """

    Notes
    -----
    mesh: 三角形网格
    h: 网格节点尺寸
    edgeVal: 定义在边上的值
    """

    NN = mesh.number_of_nodes() 
    NE = mesh.number_of_edges()
    NC = mesh.number_of_cells()

    edge = mesh.entity('edge')
    v = mesh.edge_tangent()/2 # 
    phi = np.ones((NE, 3), dtype=mesh.ftype)


    A = np.zeros((NN, 3, 3), dtype=mesh.ftype)
    b = np.zeros((NN, 3), dtype=mesh.ftype)

    phi[:, 1:] = v/h[edge[:, 0], None] # 边中点相对于 0 号端点的局部坐标 
    val = phi[:, :, None]*phi[:, None, :]
    np.add.at(A, (edge[:, 0], np.s_[:], np.s_[:]), val) # A^TA
    val = phi*edgeVal[:, None]
    np.add.at(b, (edge[:, 0], np.s_[:]), val)

    phi[:, 1:] = -v/h[edge[:, 1], None] # 边中点相对于 1 号端点的局部坐标 
    val = phi[:, :, None]*phi[:, None, :]
    np.add.at(A, (edge[:, 1], np.s_[:], np.s_[:]), val) # A^TA
    val = phi*edgeVal[:, None]
    np.add.at(b, (edge[:, 1], np.s_[:]), val)
    return A, b

def spr(uh, edge_value):

    """
    Notes
    -----
    给定一个解, 恢复节点处的值
    """
    mesh = uh.space.mesh

    NN = mesh.number_of_nodes()
    NE = mesh.number_of_edges()
    NC = mesh.number_of_cells()

    node = mesh.entity('node')
    edge = mesh.entity('edge')
    cell = mesh.entity('cell')
    edge2cell = mesh.ds.edge_to_cell()
    edgeVal = edge_value(uh)


    # 计算每个节点的最小二乘矩阵
    h = mesh.node_size()
    A, b = spr_edge(mesh, h, edgeVal) 

    # 处理边界点
    # 找到每个边界点对应的内部点, 把对应内部点的样本点当做边界节点的样本点

    isBdNode = mesh.ds.boundary_node_flag()
    idxMap = np.arange(NN, dtype=mesh.itype) # 节点映射数组, 自身到自身的映射

    # 找到一端是边界点, 一端是内部节点的边, 修改节点映射数组
    flag = isBdNode[edge[:, 0]] & (~isBdNode[edge[:, 1]])
    idxMap[edge[flag, 0]] = edge[flag, 1]
    flag = isBdNode[edge[:, 1]] & (~isBdNode[edge[:, 0]])
    idxMap[edge[flag, 1]] = edge[flag, 0]

    # 找到没有内部节点相邻的角点, 修改节点映射数组
    isCEdge = edge2cell[:, 0] != edge2cell[:, 1]
    isCEdge = isCEdge & isBdNode[edge[:, 0]] & isBdNode[edge[:, 1]]

    idxMap[cell[edge2cell[isCEdge, 0], edge2cell[isCEdge, 2]]] = cell[edge2cell[isCEdge, 1], edge2cell[isCEdge, 3]] 
    idxMap[cell[edge2cell[isCEdge, 1], edge2cell[isCEdge, 3]]] = cell[edge2cell[isCEdge, 0], edge2cell[isCEdge, 2]] 

    # 计算边界节点对应的最小二乘矩阵和右端
    # 注意可以直接利用对应内部节点对应的最小二乘矩阵和右端来计算边界点的系统, 
    # 它们有内在的数学关系
    c = h[idxMap[isBdNode]]/h[isBdNode] 
    xe = (node[idxMap[isBdNode]] - node[isBdNode])/h[isBdNode, None]

    A[isBdNode, 0, 0] = A[idxMap[isBdNode], 0, 0]

    A[isBdNode, 0, 1] = A[idxMap[isBdNode], 0, 0]*xe[:, 0] 
    A[isBdNode, 0, 1]+= A[idxMap[isBdNode], 0, 1]*c
    A[isBdNode, 1, 0] = A[isBdNode, 0, 1]

    A[isBdNode, 0, 2] = A[idxMap[isBdNode], 0, 0]*xe[:, 1] 
    A[isBdNode, 0, 2]+= A[idxMap[isBdNode], 0, 2]*c
    A[isBdNode, 2, 0] = A[isBdNode, 0, 2]

    A[isBdNode, 1, 1] = A[idxMap[isBdNode], 0, 0]*xe[:, 0]**2 
    A[isBdNode, 1, 1]+= A[idxMap[isBdNode], 0, 1]*xe[:, 0]*2*c
    A[isBdNode, 1, 1]+= A[idxMap[isBdNode], 1, 1]*c**2

    A[isBdNode, 1, 2] = A[idxMap[isBdNode], 0, 0]*xe[:, 0]*xe[:, 1] 
    A[isBdNode, 1, 2]+= A[idxMap[isBdNode], 0, 1]*xe[:, 1]*c
    A[isBdNode, 1, 2]+= A[idxMap[isBdNode], 0, 2]*xe[:, 0]*c
    A[isBdNode, 1, 2]+= A[idxMap[isBdNode], 1, 2]*c**2
    A[isBdNode, 2, 1] = A[isBdNode, 1, 2]

    A[isBdNode, 2, 2] = A[idxMap[isBdNode], 0, 0]*xe[:, 1]**2
    A[isBdNode, 2, 2]+= A[idxMap[isBdNode], 0, 2]*xe[:, 1]*2*c
    A[isBdNode, 2, 2]+= A[idxMap[isBdNode], 2, 2]*c**2

    b[isBdNode, 0] = b[idxMap[isBdNode], 0]

    b[isBdNode, 1] = b[idxMap[isBdNode], 0]*xe[:, 0]
    b[isBdNode, 1]+= b[idxMap[isBdNode], 1]*c

    b[isBdNode, 2] = b[idxMap[isBdNode], 0]*xe[:, 1]
    b[isBdNode, 2]+= b[idxMap[isBdNode], 2]*c

    A = inv(A)
    val = (A@b[:, :, None]).reshape(-1, 3)
    return val[:, 0] 


def edge_value_0(uh):
    mesh = uh.space.mesh
    edge2cell = mesh.ds.edge_to_cell()
    bc = mesh.entity_barycenter('edge')
    val0 = uh.value(bc, index=edge2cell[:, 0], barycenter=False)
    val1 = uh.value(bc, index=edge2cell[:, 1], barycenter=False)
    edgeVal = (val0 + val1)/2.0
    return edgeVal[..., 0]

def edge_value_1(uh):
    mesh = uh.space.mesh
    edge2cell = mesh.ds.edge_to_cell()
    bc = mesh.entity_barycenter('edge')
    val0 = uh.value(bc, index=edge2cell[:, 0], barycenter=False)
    val1 = uh.value(bc, index=edge2cell[:, 1], barycenter=False)
    edgeVal = (val0 + val1)/2.0
    return edgeVal[..., 1]

def edge_curl_value(uh):
    # 计算数值解在单元重心处的 curl 值
    mesh = uh.space.mesh
    bc = np.array([1/3, 1/3, 1/3], dtype=mesh.ftype)
    cellVal = uh.curl_value(bc) #(NC, )

    # 计算每条边的平均 curl 值
    edge2cell = mesh.ds.edge_to_cell()
    edgeVal = (cellVal[edge2cell[:, 0]] + cellVal[edge2cell[:, 1]])/2.0
    return edgeVal

## 参数解析
parser = argparse.ArgumentParser(description=
        """
        这是一个自适应求解时谐方程的程序, 里面有三种 pde 模型可选择
        IH: InHomogeneousData
        LS: LShapeRSinData
        CS：CosSinData
        """)

parser.add_argument('--pde',
        default='IH', type=str,
        help='pde 模型，默认是 IH 模型')

parser.add_argument('--degree', 
        default=0, type=int,
        help='第一类 Nedlec 元的次数, 默认为 0!')

parser.add_argument('--nrefine', 
        default=4, type=int,
        help='网格的初始加密次数, 默认为 4 次')

parser.add_argument('--maxit', 
        default=40, type=int,
        help='自适应迭代次数, 默认自适应迭代 40 次')

parser.add_argument('--delta', 
        default=0.02, type=float,
        help='InHomogeneousData 模型的 delta 参数, 默认为  0.02')

parser.add_argument('--theta', 
        default=0.3, type=float,
        help='自适应迭代的 theta 参数, 默认为  0.3')

parser.print_help()
args = parser.parse_args()


## 开始计算

if args.pde == 'IH':
    pde =InHomogeneousData(delta=args.delta)
elif args.pde == 'LS':
    pde = LShapeRSinData()
elif args.pde == 'CS': 
    pde = CosSinData()

mesh = pde.init_mesh(n=args.nrefine)

mesh.add_plot(plt)
plt.savefig('./test-' + str(0) + '.eps')
plt.close()

errorType = ['$|| u - u_h||_{\Omega,0}$',
             '$||\\nabla\\times u - \\nabla\\times u_h||_{\Omega, 0}$',
             '$|| u - R_h[u_h]||_{\Omega,0}$',
             '$||\\nabla\\times u - R_h[\\nabla\\times u_h]||_{\Omega, 0}$',
             'eta'
             ]
errorMatrix = np.zeros((len(errorType), args.maxit), dtype=np.float64)
NDof = np.zeros(args.maxit, dtype=np.float64)

for i in range(args.maxit):
    space = FirstKindNedelecFiniteElementSpace2d(mesh, p=args.degree)
    bc = DirichletBC(space, pde.dirichlet) 

    gdof = space.number_of_global_dofs()
    NDof[i] = gdof 

    uh = space.function()
    if args.pde != 'IH':
        A = space.curl_matrix() - space.mass_matrix()
    else:
        A = space.curl_matrix(c=pde.inv_mu) - space.mass_matrix(c=pde.epsilon)

    F = space.source_vector(pde.source)

    A, F = bc.apply(A, F, uh)

    uh[:] = spsolve(A, F)

    space = LagrangeFiniteElementSpace(mesh, p=1)
    rcuh = space.function(dim=1)
    rcuh[:] = spr(uh, edge_curl_value)  # curl 

    ruh = space.function(dim=2)
    ruh[:, 0] = spr(uh, edge_value_0) # 
    ruh[:, 1] = spr(uh, edge_value_1)

    errorMatrix[0, i] = space.integralalg.L2_error(pde.solution, uh)
    errorMatrix[1, i] = space.integralalg.L2_error(pde.curl, uh.curl_value)
    errorMatrix[2, i] = space.integralalg.L2_error(pde.solution, ruh)
    errorMatrix[3, i] = space.integralalg.L2_error(pde.curl, rcuh)

    # 计算单元上的恢复型误差
    eta0 = space.integralalg.error(uh.curl_value, 
            rcuh, power=2, celltype=True) # eta_K
    eta1 = space.integralalg.error(uh.value,  
            ruh, power=2, celltype=True) # xi_K
    eta = np.sqrt(eta0**2 + eta1**2) # S_K
    errorMatrix[4, i] = np.sqrt(np.sum(eta**2)) # S_h
    if i < args.maxit - 1:
        isMarkedCell = mark(eta, theta=args.theta)
        mesh.bisect(isMarkedCell)
        mesh.add_plot(plt)
        plt.savefig('./test-' + str(i+1) + '.eps')
        plt.close()

showmultirate(plt, args.maxit-10, NDof, errorMatrix,  errorType, propsize=6)
plt.savefig('./error.eps')
plt.show()
