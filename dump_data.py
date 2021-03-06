#!/usr/bin/env python3
# dump_data.py ---
#
# Filename: dump_data.py
# Description:
# Author: Kwang Moo Yi
# Maintainer:
# Created: Mon Apr  2 18:33:34 2018 (-0700)
# Version:
# Package-Requires: ()
# URL:
# Doc URL:
# Keywords:
# Compatibility:
#
#

# Commentary:
#
#
#
#

# Change Log:
#
#
#
# Copyright (C)
# Visual Computing Group @ University of Victoria
# Computer Vision Lab @ EPFL

# Code:


from __future__ import print_function

import itertools
import multiprocessing as mp
import os
import pickle
import sys
import time

import numpy as np

import cv2
from config import get_config
from data import loadFromDir
from geom import get_episqr, get_episym, get_sampsons, parse_geom
from six.moves import xrange
from utils import loadh5, saveh5, embed_breakpoint

eps = 1e-10
use3d = False
config = None

config, unparsed = get_config()


def dump_data_pair(args):
    dump_dir, idx, ii, jj, queue = args

    # queue for monitoring
    if queue is not None:
        queue.put(idx)

    dump_file = os.path.join(
        dump_dir, "idx_sort-{}-{}.h5".format(ii, jj))

    if not os.path.exists(dump_file):
        # Load descriptors for ii
        desc_ii = loadh5(
            os.path.join(dump_dir, "kp-z-desc-{}.h5".format(ii)))["desc"]
        desc_jj = loadh5(
            os.path.join(dump_dir, "kp-z-desc-{}.h5".format(jj)))["desc"]
        # compute decriptor distance matrix
        distmat = np.sqrt(
            np.sum(
                (np.expand_dims(desc_ii, 1) - np.expand_dims(desc_jj, 0))**2,
                axis=2))
        # Choose K best from N
        idx_sort = np.argsort(distmat, axis=1)[:, :config.obj_num_nn]
        idx_sort = (
            np.repeat(
                np.arange(distmat.shape[0])[..., None],
                idx_sort.shape[1], axis=1
            ),
            idx_sort
        )
        distmat = distmat[idx_sort]
        # Dump to disk
        dump_dict = {}
        dump_dict["idx_sort"] = idx_sort
        saveh5(dump_dict, dump_file)


def make_xy(num_sample, pairs, kp, z, desc, img, geom, vis, depth, geom_type,
            cur_folder):

    xs = []
    ys = []
    Rs = []
    ts = []
    img1s = []
    img2s = []
    cx1s = []
    cy1s = []
    f1s = []
    cx2s = []
    cy2s = []
    f2s = []

    # Create a random folder in scratch
    dump_dir = os.path.join(cur_folder, "dump")
    if not os.path.exists(dump_dir):
        os.makedirs(dump_dir)

    # randomly suffle the pairs and select num_sample amount
    np.random.seed(1234)
    cur_pairs = [
        pairs[_i] for _i in np.random.permutation(len(pairs))[:num_sample]
    ]
    idx = 0
    for ii, jj in cur_pairs:
        idx += 1
        print(
            "\rExtracting keypoints {} / {}".format(idx, len(cur_pairs)),
            end="")
        sys.stdout.flush()

        # Check and extract keypoints if necessary
        for i in [ii, jj]:
            dump_file = os.path.join(dump_dir, "kp-z-desc-{}.h5".format(i))
            if not os.path.exists(dump_file):
                if kp[i] is None:
                    assert config.precomputed_kp_method is None, 'please load and use precomputed keypionts'
                    xy, cv_desc = compute_sift(img[i])
                    cx, cy, fx, fy = compute_intrinsics(img, i, geom, geom_type)
                    kp[i] = (
                        xy - np.array([[cx, cy]])
                    ) / np.asarray([[fx, fy]])
                    desc[i] = cv_desc
                if z[i] is None:
                    z[i] = compute_z_value(img, i, geom, geom_type, kp, depth)
                # Write descs to harddisk to parallize
                dump_dict = {}
                dump_dict["kp"] = kp[i]
                dump_dict["z"] = z[i]
                dump_dict["desc"] = desc[i]
                saveh5(dump_dict, dump_file)
            else:
                dump_dict = loadh5(dump_file)
                kp[i] = dump_dict["kp"]
                z[i] = dump_dict["z"]
                desc[i] = dump_dict["desc"]
    print("")

    # Create arguments
    pool_arg, queue = create_pool_arg(cur_pairs, dump_dir)
    # Run mp job
    pool = create_mp_pool()
    # map async
    pool_res = pool.map_async(dump_data_pair, pool_arg)
    # monitor loop
    while True:
        if pool_res.ready():
            break
        else:
            size = queue.qsize()
            print("\rDistMat {} / {}".format(size, len(pool_arg)), end="")
            sys.stdout.flush()
            time.sleep(1)
    pool.close()
    pool.join()
    print("")
    # Pack data
    idx = 0
    total_num = 0
    good_num = 0
    bad_num = 0
    for ii, jj in cur_pairs:
        idx += 1
        print("\rWorking on {} / {}".format(idx, len(cur_pairs)), end="")
        sys.stdout.flush()

        # ------------------------------
        # Get dR
        R_i = parse_geom(geom, geom_type)["R"][ii]
        R_j = parse_geom(geom, geom_type)["R"][jj]
        dR = np.dot(R_j, R_i.T)
        # Get dt
        t_i = parse_geom(geom, geom_type)["t"][ii].reshape([3, 1])
        t_j = parse_geom(geom, geom_type)["t"][jj].reshape([3, 1])
        dt = t_j - np.dot(dR, t_i)
        # ------------------------------
        # Get sift points for the first image
        x1 = kp[ii]
        y1 = np.concatenate([kp[ii] * z[ii], z[ii]], axis=1)
        # Project the first points into the second image
        y1p = np.matmul(dR[None], y1[..., None]) + dt[None]
        # move back to the canonical plane
        x1p = y1p[:, :2, 0] / y1p[:, 2, 0][..., None]
        # ------------------------------
        # Get sift points for the second image
        x2 = kp[jj]
        # # DEBUG ------------------------------
        # # Check if the image projections make sense
        # draw_val_res(
        #     img[ii],
        #     img[jj],
        #     x1, x1p, np.random.rand(x1.shape[0]) < 0.1,
        #     (img[ii][0].shape[1] - 1.0) * 0.5,
        #     (img[ii][0].shape[0] - 1.0) * 0.5,
        #     parse_geom(geom, geom_type)["K"][ii, 0, 0],
        #     (img[jj][0].shape[1] - 1.0) * 0.5,
        #     (img[jj][0].shape[0] - 1.0) * 0.5,
        #     parse_geom(geom, geom_type)["K"][jj, 0, 0],
        #     "./debug_imgs/",
        #     "debug_img{:04d}.png".format(idx)
        # )
        # ------------------------------
        # create x1, y1, x2, y2 as a matrix combo
        x1mat = np.repeat(x1[:, 0][..., None], len(x2), axis=-1)
        y1mat = np.repeat(x1[:, 1][..., None], len(x2), axis=1)
        x1pmat = np.repeat(x1p[:, 0][..., None], len(x2), axis=-1)
        y1pmat = np.repeat(x1p[:, 1][..., None], len(x2), axis=1)
        x2mat = np.repeat(x2[:, 0][None], len(x1), axis=0)
        y2mat = np.repeat(x2[:, 1][None], len(x1), axis=0)
        # Load precomputed nearest neighbors
        idx_sort = loadh5(os.path.join(
            dump_dir, "idx_sort-{}-{}.h5".format(ii, jj)))["idx_sort"]
        # Move back to tuples
        idx_sort = (idx_sort[0], idx_sort[1])
        x1mat = x1mat[idx_sort]
        y1mat = y1mat[idx_sort]
        x1pmat = x1pmat[idx_sort]
        y1pmat = y1pmat[idx_sort]
        x2mat = x2mat[idx_sort]
        y2mat = y2mat[idx_sort]
        # Turn into x1, x1p, x2
        x1 = np.concatenate(
            [x1mat.reshape(-1, 1), y1mat.reshape(-1, 1)], axis=1)
        x1p = np.concatenate(
            [x1pmat.reshape(-1, 1),
             y1pmat.reshape(-1, 1)], axis=1)
        x2 = np.concatenate(
            [x2mat.reshape(-1, 1), y2mat.reshape(-1, 1)], axis=1)

        # make xs in NHWC
        xs += [
            np.concatenate([x1, x2], axis=1).T.reshape(4, 1, -1).transpose(
                (1, 2, 0))
        ]

        # ------------------------------
        # Get the geodesic distance using with x1, x2, dR, dt
        if config.obj_geod_type == "sampson":
            geod_d = get_sampsons(x1, x2, dR, dt)
        elif config.obj_geod_type == "episqr":
            geod_d = get_episqr(x1, x2, dR, dt)
        elif config.obj_geod_type == "episym":
            geod_d = get_episym(x1, x2, dR, dt)
        # Get *rough* reprojection errors. Note that the depth may be noisy. We
        # ended up not using this...
        reproj_d = np.sum((x2 - x1p)**2, axis=1)
        # count inliers and outliers
        total_num += len(geod_d)
        good_num += np.sum((geod_d < config.obj_geod_th))
        bad_num += np.sum((geod_d >= config.obj_geod_th))
        ys += [np.stack([geod_d, reproj_d], axis=1)]
        # Save R, t for evaluation
        Rs += [np.array(dR).reshape(3, 3)]
        # normalize t before saving
        dtnorm = np.sqrt(np.sum(dt**2))
        assert (dtnorm > 1e-5)
        dt /= dtnorm
        ts += [np.array(dt).flatten()]

        # Save img1 and img2 for display
        img1s += [img[ii]]
        img2s += [img[jj]]
        cx, cy, fx, fy = compute_intrinsics(img, ii, geom, geom_type)
        if np.isclose(fx, fy):
            f = fx
        else:
            f = (fx, fy)
        cx1s += [cx]
        cy1s += [cy]
        f1s += [f]
        cx, cy, fx, fy = compute_intrinsics(img, jj, geom, geom_type)
        if np.isclose(fx, fy):
            f = fx
        else:
            f = (fx, fy)
        cx2s += [cx]
        cy2s += [cy]
        f2s += [f]

    # Do *not* convert to numpy arrays, as the number of keypoints may differ
    # now. Simply return it
    print(".... done")
    if total_num > 0:
        print(" Good pairs = {}, Total pairs = {}, Ratio = {}".format(
            good_num, total_num, float(good_num) / float(total_num)))
        print(" Bad pairs = {}, Total pairs = {}, Ratio = {}".format(
            bad_num, total_num, float(bad_num) / float(total_num)))

    res_dict = {}
    res_dict["xs"] = xs
    res_dict["ys"] = ys
    res_dict["Rs"] = Rs
    res_dict["ts"] = ts
    res_dict["img1s"] = img1s
    res_dict["cx1s"] = cx1s
    res_dict["cy1s"] = cy1s
    res_dict["f1s"] = f1s
    res_dict["img2s"] = img2s
    res_dict["cx2s"] = cx2s
    res_dict["cy2s"] = cy2s
    res_dict["f2s"] = f2s

    return res_dict

def create_pool_arg(cur_pairs, dump_dir):
    # Create arguments
    pool_arg = []
    idx = 0
    for ii, jj in cur_pairs:
        idx += 1
        pool_arg += [(dump_dir, idx, ii, jj)]
    manager = mp.Manager()
    queue = manager.Queue()
    for idx_arg in xrange(len(pool_arg)):
        pool_arg[idx_arg] = pool_arg[idx_arg] + (queue,)
    return pool_arg, queue

def create_mp_pool():
    # Run mp job
    ratio_CPU = 0.4
    # number_of_process = 4
    number_of_process = int(ratio_CPU * mp.cpu_count())
    pool = mp.Pool(processes=number_of_process)
    return pool

def compute_z_value(img, i, geom, geom_type, kp, depth):
    cx = (img[i][0].shape[1] - 1.0) * 0.5
    cy = (img[i][0].shape[0] - 1.0) * 0.5
    fx = parse_geom(geom, geom_type)["K"][i, 0, 0]
    fy = parse_geom(geom, geom_type)["K"][i, 1, 1]
    xy = kp[i] * np.asarray([[fx, fy]]) + np.array([[cx, cy]])
    if len(depth) > 0:
        cz = depth[i][
            0,
            np.round(xy[:, 1]).astype(int),
            np.round(xy[:, 0]).astype(int)][..., None]
    else:
        cz = np.ones((xy.shape[0], 1))
    return cz

def compute_sift(img):
    cv_kp, cv_desc = sift.detectAndCompute(img.transpose(
        1, 2, 0), None)
    xy = np.array([_kp.pt for _kp in cv_kp])
    return xy, cv_desc

def compute_intrinsics(img, i, geom, geom_type):
    h, w = img[i].shape[1:]
    cx = (w - 1.0) * 0.5
    cy = (h - 1.0) * 0.5
    # Correct coordinates using K
    Ks = parse_geom(geom, geom_type)["K"]
    cx += Ks[i, 0, 2]
    cy += Ks[i, 1, 2]

    # Correct focals
    fx = Ks[i, 0, 0]
    fy = Ks[i, 1, 1]
    # exec(embed_breakpoint())
    return cx, cy, fx, fy


print("-------------------------DUMP-------------------------")
print("Note: dump_data.py will only work on the first dataset")

# Read conditions
crop_center = config.data_crop_center
data_folder = config.data_dump_prefix
if config.precomputed_kp_method:
    data_folder += config.precomputed_kp_method

# Prepare opencv
print("Creating Opencv SIFT instance")
if not config.precomputed_kp_method:
    sift = cv2.xfeatures2d.SIFT_create(
        nfeatures=config.obj_num_kp, contrastThreshold=1e-5)

# Now start data prep
print("Preparing data for {}".format(config.data_tr.split(".")[0]))

for _set in ["train", "valid", "test"]:
    num_sample = getattr(
        config, "train_max_{}_sample".format(_set[:2]))

    # Load the data
    print("Loading Raw Data for {}".format(_set))
    if _set == "valid":
        split = "val"
    else:
        split = _set
    img, geom, vis, depth, kp, desc = loadFromDir(
        getattr(config, "data_dir_" + _set[:2]) + split + "/",
        "-16x16",
        bUseColorImage=True,
        crop_center=crop_center,
        precomputed_kp_method=config.precomputed_kp_method)
    if len(kp) == 0:
        kp = [None] * len(img)
    if len(desc) == 0:
        desc = [None] * len(img)
    z = [None] * len(img)

    # Generating all possible pairs
    print("Generating list of all possible pairs for {}".format(_set))
    pairs = []
    for ii, jj in itertools.product(xrange(len(img)), xrange(len(img))):
        if ii != jj:
            if vis[ii][jj] > getattr(config, "data_vis_th_" + _set[:2]):
                pairs.append((ii, jj))
    print("{} pairs generated".format(len(pairs)))

    # Create data dump directory name
    data_names = getattr(config, "data_" + _set[:2])
    data_name = data_names.split(".")[0]
    cur_data_folder = "/".join([
        data_folder,
        data_name,
        "numkp-{}".format(config.obj_num_kp),
        "nn-{}".format(config.obj_num_nn),
    ])
    if not config.data_crop_center:
        cur_data_folder = os.path.join(cur_data_folder, "nocrop")
    if not os.path.exists(cur_data_folder):
        os.makedirs(cur_data_folder)
    suffix = "{}-{}".format(
        _set[:2], getattr(config, "train_max_" + _set[:2] + "_sample"))
    cur_folder = os.path.join(cur_data_folder, suffix)
    if not os.path.exists(cur_folder):
        os.makedirs(cur_folder)

    # Check if we've done this folder already.
    print(" -- Waiting for the data_folder to be ready")
    ready_file = os.path.join(cur_folder, "ready")
    if not os.path.exists(ready_file):
        print(" -- No ready file {}".format(ready_file))
        print(" -- Generating data")

        # Make xy for this pair
        data_dict = make_xy(
            num_sample, pairs, kp, z, desc,
            img, geom, vis, depth, getattr(
                config, "data_geom_type_" + _set[:2]),
            cur_folder)

        # Let's pickle and save data. Note that I'm saving them
        # individually. This was to have flexibility, but not so much
        # necessary.
        for var_name in data_dict:
            cur_var_name = var_name + "_" + _set[:2]
            out_file_name = os.path.join(cur_folder, cur_var_name) + ".pkl"
            with open(out_file_name, "wb") as ofp:
                pickle.dump(data_dict[var_name], ofp)

        # Mark ready
        with open(ready_file, "w") as ofp:
            ofp.write("This folder is ready\n")
    else:
        print("Done!")

#
# dump_data.py ends here
