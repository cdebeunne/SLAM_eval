import numpy as np
from matplotlib import pyplot as plt
import csv
import pandas as pd
from scipy.spatial.transform import Rotation
import os
from glob import glob
import pickle

from kitti_odometry import EvalOdom, umeyama_alignment, gt_alignment, full_alignment
from data_parser import *


class IsaeEvalOdom(EvalOdom):
    """Evaluate isae odometry result
    Usage example:
        vo_eval = IsaeEvalOdom()
        vo_eval.eval(gt_pose_txt_dir, result_pose_txt_dir)
    """

    def compute_scale_error(self, gt, pred):
        """Compute scale error
        Args:
            gt (4x4 array dict): ground-truth poses
            pred (4x4 array dict): predicted poses
        Returns:
            scale errors
        """
        scale_errors = []

        for i in list(pred.keys())[:-1]:
            gt1 = gt[i]
            gt2 = gt[i+1]
            gt_rel = np.linalg.inv(gt1) @ gt2

            pred1 = pred[i]
            pred2 = pred[i+1]
            pred_rel = np.linalg.inv(pred1) @ pred2
            
            # print(i, " : ", self.scale_error(gt_rel, pred_rel))

            scale_errors.append(self.scale_error(gt_rel, pred_rel))
        return scale_errors

    def compute_scale_ratio(self, gt, pred):
        """Compute scale ration
        Args:
            gt (4x4 array dict): ground-truth poses
            pred (4x4 array dict): predicted poses
        Returns:
            scale ratios
        """
        scale_ratios = []
        length = 0

        for i in list(pred.keys())[:-1]:
            gt1 = gt[i]
            gt2 = gt[i+1]
            gt_rel = np.linalg.inv(gt1) @ gt2

            pred1 = pred[i]
            pred2 = pred[i+1]
            pred_rel = np.linalg.inv(pred1) @ pred2

            length += np.linalg.norm(gt_rel[0:3, 3])

            if (np.linalg.norm(gt_rel[0:3, 3]) < 0.05):
                continue

            scale_ratios.append(self.scale_ratio(gt_rel, pred_rel))
        
        print("Length : ", length)

        return scale_ratios


    def eval(self, gt_dir, result_dir,
             alignment=None,
             seqs=None,
             filename=None,
             length=-1):
        """Evaulate required/available sequences
        Args:
            gt_dir (str): ground truth poses txt files directory
            result_dir (str): pose predictions txt files directory
            alignment (str): if not None, optimize poses by
                - scale: optimize scale factor for trajectory alignment and evaluation
                - scale_7dof: optimize 7dof for alignment and use scale for trajectory evaluation
                - 7dof: optimize 7dof for alignment and evaluation
                - 6dof: optimize 6dof for alignment and evaluation
            seqs (list/None):
                - None: Evalute all available seqs in result_dir
                - list: list of sequence indexs to be evaluated
        """
        seq_list = ["C1", "C3", "C4", "C5", "demo_coax", "demo_mars",
                    "nonoverlapping_test", "nonoverlapping_cave", "chariot1", "chariot2", "chariot3", "chariot4",
                    "traj_3", "traj_4", "sar1", "tour_butte2", "grand_tour"]

        # Initialization
        self.gt_dir = gt_dir
        seq_ate = []
        seq_rpe_trans = []
        seq_rpe_rot = []

        # Create evaluation list
        if seqs is None:
            available_seqs = [os.path.basename(x).rsplit(
                ".", 1)[0] for x in glob(result_dir+'/*.csv')]
            self.eval_seqs = [i for i in available_seqs if i in seq_list]
        else:
            self.eval_seqs = seqs

        # evaluation
        for i in self.eval_seqs:

            self.cur_seq = i
            # Read pose txt
            self.cur_seq = '{}'.format(i)
            gt_file_name = '{}.csv'.format(i)

            if (filename is None):
                result_file_name = '{}.csv'.format(i)
            else:
                result_file_name = filename

            poses_result, timestamp_result = load_poses_from_csv_isae(
                result_dir + "/" + result_file_name)
            poses_gt, timestamp_gt = load_poses_from_csv_isae(
                self.gt_dir + "/" + gt_file_name)
            self.result_file_name = result_dir + result_file_name

            df_result = pd.DataFrame({
                "timestamp": timestamp_result
            })
            
            df_gt = pd.DataFrame({
                "timestamp": timestamp_gt
            })

            poses_gt_sync = {}
            counter = 0
            for ts in df_result['timestamp']:
                
                idx = df_gt['timestamp'].sub(float(ts)).abs().idxmin()
                poses_gt_sync[counter] = poses_gt[idx]

                counter += 1
            poses_gt = poses_gt_sync

            # Pose alignment to first frame
            idx_0 = sorted(list(poses_result.keys()))[0]
            pred_0 = poses_result[idx_0]
            gt_0 = poses_gt[idx_0]
            for cnt in poses_result:
                poses_result[cnt] = np.linalg.inv(pred_0) @ poses_result[cnt]
                poses_gt[cnt] = np.linalg.inv(gt_0) @ poses_gt[cnt]

            if alignment == "scale":
                poses_result = self.scale_optimization(poses_gt, poses_result)
            elif alignment == "scale_7dof" or alignment == "7dof" or alignment == "6dof":
                # get XYZ
                xyz_gt = []
                xyz_result = []
                for cnt in poses_result:
                    xyz_gt.append(
                        [poses_gt[cnt][0, 3], poses_gt[cnt][1, 3], poses_gt[cnt][2, 3]])
                    xyz_result.append(
                        [poses_result[cnt][0, 3], poses_result[cnt][1, 3], poses_result[cnt][2, 3]])
                xyz_gt = np.asarray(xyz_gt).transpose(1, 0)
                xyz_result = np.asarray(xyz_result).transpose(1, 0)

                r, t, scale = umeyama_alignment(
                    xyz_result, xyz_gt, alignment != "6dof")

                align_transformation = np.eye(4)
                align_transformation[:3:, :3] = r
                align_transformation[:3, 3] = t

                for cnt in poses_result:
                    poses_result[cnt][:3, 3] *= scale
                    if alignment == "7dof" or alignment == "6dof":
                        poses_result[cnt] = align_transformation @ poses_result[cnt]
            
            poses_gt = full_alignment(poses_result, poses_gt)

            # Compute ATE
            ate = self.compute_ATE(poses_gt, poses_result)
            seq_ate.append(ate)
            print(i)
            print("ATE (m): ", ate)

            # Compute RPE
            rpe_trans, rpe_rot = self.compute_RPE(poses_gt, poses_result)
            # avg_scale_err = np.mean(np.asarray(self.compute_scale_error(poses_gt, poses_result)))
            seq_rpe_trans.append(rpe_trans)
            seq_rpe_rot.append(rpe_rot)
            print("RPE (m): ", rpe_trans)
            print("RPE (deg): ", rpe_rot * 180 / np.pi)
            # print("Scale : ", avg_scale_err)

            # Plotting
            self.plot_path_dir = result_dir + "/plot_path"
            self.plot_trajectory(poses_gt, poses_result, self.cur_seq)
            self.compute_scale_ratio(poses_gt, poses_result)

        return [ate, rpe_trans]

    def plot_trajectory(self, poses_gt, poses_result, seq):
        """Plot trajectory for both GT and prediction
        Args:
            poses_gt (dict): {idx: 4x4 array}; ground truth poses
            poses_result (dict): {idx: 4x4 array}; predicted poses
            seq (int): sequence index.
        """
        plot_keys = ["Ground Truth", "Ours"]
        fontsize_ = 20

        poses_dict = {}
        poses_dict["Ground Truth"] = poses_gt
        poses_dict["Ours"] = poses_result
        
        # Write in a csv
        pose_df = pd.DataFrame(poses_dict)

        fig = plt.figure()
        ax = plt.gca()
        ax.set_aspect('equal')

        for key in plot_keys:
            pos_xy = []
            frame_idx_list = sorted(poses_dict["Ours"].keys())
            for frame_idx in frame_idx_list:
                # pose = np.linalg.inv(poses_dict[key][frame_idx_list[0]]) @ poses_dict[key][frame_idx]
                pose = poses_dict[key][frame_idx]
                pos_xy.append([pose[0, 3],  pose[1, 3]])
            pos_xy = np.asarray(pos_xy)
            plt.plot(pos_xy[:, 0],  pos_xy[:, 1], label=key)

        plt.legend(loc="upper right", prop={'size': fontsize_})
        plt.xticks(fontsize=fontsize_)
        plt.yticks(fontsize=fontsize_)
        plt.xlabel('x (m)', fontsize=fontsize_)
        plt.ylabel('y (m)', fontsize=fontsize_)
        fig.set_size_inches(10, 10)
        png_title = "sequence_{}".format(seq)
        fig_pdf = self.plot_path_dir + "/" + png_title + ".pdf"
        plt.savefig(fig_pdf, bbox_inches='tight', pad_inches=0)
        plt.close(fig)

    def plot_scale_error(self, poses_gt, poses_result, seq):

        fig = plt.figure()
        ax = plt.gca()
        fontsize_ = 12

        scale_ratio = self.compute_scale_ratio(poses_gt, poses_result)

        # Write in a csv
        # scale_df = pd.DataFrame(scale_ratio)
        # scale_df.to_csv('scale.csv')

        plt.plot(scale_ratio, "*", color='red')
        plt.xlabel('Keyframes', fontsize=fontsize_)
        plt.ylabel('Scale ratio', fontsize=fontsize_)
        ax.set_ylim([0, 2])
        plt.show()

