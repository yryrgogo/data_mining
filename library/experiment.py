import sys
import numpy as np
import pandas as pd
import shutil
from hyperopt import fmin, tpe, hp, STATUS_OK, Trials
from tqdm import tqdm
#  from select_feature import move_to_second_valid

sys.path.append('../model')
from Estimator import prediction, cross_validation, data_check
from params_lgbm import train_params


def much_feature_validation(base, path, move_path, dummie=0, val_col='valid_no'):

    feature_list = np.array(glob.glob('../features/1_first_valid/*.npy'))
    feature_list = np.sort(feature_list)
    if len(feature_list)>1000:
        feature_list = feature_list[:1000]

    for feature in feature_list:
        shutil.move(feature, '../features/3_winner/')

    logger.info(f'move feature:{len(feature_list)}')

    key_list = []
    for rank in rank_list:
        logger.info(f'rank:{rank}')
        _, _, importance = first_train(base, path, dummie=0, val_col=val_col)
        move_to_second_valid(best_select=importance, rank=rank, key_list=key_list)


def first_train(
        logger,
        train,
        key,
        target,
        fold_type='stratified',
        fold=5,
        group_col_name='',
        val_label='val_label',
        params={},
        num_boost_round=2000,
        early_stopping_rounds=50,
        metric='',
        model_type='lgb',
        dummie=0,
        ignore_list=[],
        judge_flg=False,
):

    train, _ = data_check(logger, train, target, dummie=dummie, ignore_list=ignore_list)

    cv_feim, col_length = cross_validation(
        logger=logger,
        train=train,
        key=key,
        target=target,
        fold_type=fold_type,
        fold=fold,
        group_col_name=group_col_name,
        val_label=val_label,
        params=params,
        num_boost_round=2000,
        early_stopping_rounds=50,
        metric=metric,
        model_type=model_type,
        ignore_list=ignore_list,
        judge_flg=judge_flg
    )
    importance = cv_feim[['feature', 'avg_importance', 'rank']].sort_values(by='avg_importance')

    return cv_feim, train, importance
