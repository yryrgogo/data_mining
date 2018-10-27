Pararell=True
import numpy as np
"""
基底クラス
"""
from abc import ABCMeta, abstractmethod
import numpy as np
import pandas as pd
from sklearn.metrics import log_loss, roc_auc_score, mean_squared_error, r2_score
from sklearn.model_selection import ParameterGrid, StratifiedKFold, GroupKFold, KFold
import multiprocessing
import shutil
import gc
from scipy.stats.mstats import mquantiles
from tqdm import tqdm
import sys
import os
HOME = os.path.expanduser('~')
sys.path.append(f"{HOME}/kaggle/data_analysis/library/")
from pararell_utils import pararell_process
from caliculate_utils import round_size
from preprocessing import factorize_categoricals, get_dummies

kaggle = 'home-credit-default-risk'


class Model(metaclass=ABCMeta):
    @abstractmethod
    def train(self):
        pass

    @abstractmethod
    def predict(self):
        pass

    #  @abstractmethod
    def predict_proba(self):
        pass

    #  @abstractmethod
    def accuracy(self):
        pass

    #  @abstractmethod
    def cross_validation(self):
        pass

    #  @abstractmethod
    def cross_val_score(self):
        pass

    def sc_metrics(self, y_test, y_pred):
        if self.metric == 'logloss':
            return log_loss(y_test, y_pred)
        elif self.metric == 'auc':
            return roc_auc_score(y_test, y_pred)
        elif self.metric=='l2':
            return r2_score(y_test, y_pred)
        elif self.metric=='rmse':
            return np.sqrt(mean_squared_error(y_test, y_pred))
        else:
            print('SCORE CALICULATION ERROR!')

    def auc(self, test_features, test_target):
        return roc_auc_score(test_target, self.predict(test_features))

    def feature_impact(self):
        pass


    def df_feature_importance(self, feim_name):
        ' Feature Importance '
        if self.model_type.count('lgb'):
            tmp_feim = pd.Series(self.estimator.feature_importance(), name=feim_name)
            feature_name = pd.Series(self.use_cols, name='feature')
            feim = pd.concat([feature_name, tmp_feim], axis=1)
        elif self.model_type.count('xgb'):
            tmp_feim = self.estimator.get_fscore()
            feim = pd.Series(tmp_feim,  name=feim_name).to_frame().reset_index().rename(columns={'index':'feature'})
        elif self.model_type.count('ext'):
            tmp_feim = self.estimator.feature_importance_()
            feim = pd.Series(tmp_feim,  name=feim_name).to_frame().reset_index().rename(columns={'index':'feature'})
        return feim


    def move_feature(self, feature_name, move_path='../features/9_delete'):

        try:
            shutil.move(f'../features/4_winner/{feature_name}.gz', move_path)
        except FileNotFoundError:
            print(f'FileNotFound. : {feature_name}.gz')
            pass


    def data_check(self, df, test_flg=False, cat_encode=True, dummie=0, exclude_category=False):
        '''
        Explain:
            学習を行う前にデータに問題がないかチェックする
            カテゴリカルなデータが入っていたらエンコーディング or Dropする
        Args:
        Return:
        '''

        categorical_list = [col for col in list(df.columns) if (df[col].dtype == 'object') and col not in self.ignore_list]
        dt_list = [col for col in list(df.columns) if str(df[col].dtype).count('time') and col not in self.ignore_list]
        self.logger.info(f'''
#==============================================================================
# DATA CHECK START
# CATEGORICAL FEATURE: {categorical_list}
# DATETIME FEATURE   : {dt_list}
# CAT ENCODE         : {cat_encode}
# DUMMIE             : {dummie}
# ignore_list        : {self.ignore_list}
#==============================================================================
        ''')

        if cat_encode:
            ' 対象カラムのユニーク数が100より大きかったら、ラベルエンコーディングにする '
            label_list = []
            for cat in categorical_list:
                if df[cat].nunique()>100:
                    label_list.append(cat)
                    categorical_list.remove(cat)
                df = factorize_categoricals(df, label_list)

            if exclude_category:
                for cat in categorical_list:
                    df.drop(cat, axis=1, inplace=True)
                    self.move_feature(feature_name=cat)
                categorical_list = []
            elif dummie==1:
                df = get_dummies(df, categorical_list)
                categorical_list=[]
            elif dummie==0:
                df = factorize_categoricals(df, categorical_list)
                categorical_list=[]

        ' Testsetで値のユニーク数が1のカラムを除外する '
        drop_list = []
        if test_flg:
            for col in df.columns:
                length = df[col].nunique()
                if length <=1 and col not in self.ignore_list:
                    self.logger.info(f'''
***********WARNING************* LENGTH {length} COLUMN: {col}''')
                    self.move_feature(feature_name=col)
                    if col not in self.ignore_list:
                        drop_list.append(col)

        self.logger.info(f'''
#==============================================================================
# DATA CHECK END
# SHAPE: {df.shape}
#==============================================================================''')

        return df, drop_list


    def cross_prediction(self, train, test, key, target, fold_type='stratified', fold=5, group_col_name='', params={}, num_boost_round=0, early_stopping_rounds=0, oof_flg=True):

        # Result Variables
        list_score = []
        cv_feim = pd.DataFrame([])
        prediction = np.array([])

        # Y Setting
        if params['objective'] == 'regression':
            y = train[target].astype('float64')
            y = np.log1p(y)
        else:
            y = train[target]

        ' KFold '
        if fold_type == 'stratified':
            folds = StratifiedKFold(n_splits=fold, shuffle=True, random_state=self.seed)  # 1
            kfold = folds.split(train, y)
        elif fold_type == 'group':
            if group_col_name == '':
                raise ValueError(f'Not exist group_col_name.')
            folds = GroupKFold(n_splits=fold)
            kfold = folds.split(train, y, groups=train[group_col_name].values)
        elif fold_type == 'kfold':
            folds = KFold(n_splits=fold, shuffle=True, random_state=self.seed)  # 1
            kfold = folds.split(train, y)

        use_cols = [f for f in train.columns if f not in self.ignore_list]
        self.use_cols = sorted(use_cols)  # カラム名をソートし、カラム順による学習への影響をなくす

        if kaggle == 'ga' and 'unique_id' in list(train.columns):
                train.set_index(['unique_id', key], inplace=True)
                test.set_index(['unique_id', key], inplace=True)
        else:
            train.set_index(key, inplace=True)
            test.set_index(key, inplace=True)

        for n_fold, (trn_idx, val_idx) in enumerate(kfold):

            x_train, y_train = train[self.use_cols].iloc[trn_idx, :], y.iloc[trn_idx].values
            x_val, y_val = train[self.use_cols].iloc[val_idx, :], y.iloc[val_idx].values

            if self.model_type.count('xgb'):
                " XGBは'[]'と','と'<>'がNGなのでreplace "
                if i == 0:
                    test = test[self.use_cols]
                use_cols = []
                for col in x_train.columns:
                    use_cols.append(col.replace(
                        "[", "-q-").replace("]", "-p-").replace(",", "-o-"))
                use_cols = sorted(use_cols)
                x_train.columns = use_cols
                x_val.columns = use_cols
                test.columns = use_cols
                self.use_cols = use_cols

            if n_fold == 0:
                test = test[self.use_cols]

            # GBDTのみ適用するargs
            gbdt_args = {}
            if num_boost_round:
                gbdt_args['num_boost_round'] = num_boost_round
                gbdt_args['early_stopping_rounds'] = early_stopping_rounds
            self.estimator = self.train(
                x_train=x_train,
                y_train=y_train,
                x_val=x_val,
                y_val=y_val,
                params=params,
                gbdt_args=gbdt_args
            )
            y_pred = self.estimator.predict(x_val)

            self.fold_model_list.append(self.estimator)

            if kaggle == 'ga':
                hits = x_val['totals-hits'].map(lambda x: 0 if x ==
                                                1 else 1).values
                bounces = x_val['totals-bounces'].map(
                    lambda x: 0 if x == 1 else 1).values
                y_pred = y_pred * hits * bounces
                if self.metric == 'rmse':
                    y_pred[y_pred < 0.1] = 0

            sc_score = self.sc_metrics(y_val, y_pred)

            list_score.append(sc_score)
            self.logger.info(f'Fold No: {n_fold} | {self.metric}: {sc_score}')

            ' OOF for Stackng '
            if oof_flg:
                val_pred = y_pred
                if n_fold == 0:
                    if kaggle == 'ga':
                        val_stack = x_val.reset_index()[['unique_id', key]]
                    else:
                        val_stack = x_val.reset_index()[key].to_frame()
                    val_stack[target] = val_pred
                else:
                    if kaggle == 'ga':
                        tmp = x_val.reset_index()[['unique_id', key]]
                    else:
                        tmp = x_val.reset_index()[key].to_frame()
                    tmp[target] = val_pred
                    val_stack = pd.concat([val_stack, tmp], axis=0)

            if not(self.model_type.count('xgb')):
                test_pred = self.estimator.predict(test)
            elif self.model_type.count('xgb'):
                test_pred = self.estimator.predict(xgb.DMatrix(test))

            if params['objective']=='regression':
                test_pred = np.expm1(test_pred)

            if len(prediction) == 0:
                prediction = test_pred
            else:
                prediction += test_pred

            ' Feature Importance '
            feim_name = f'{n_fold}_importance'
            feim = self.df_feature_importance(feim_name=feim_name)

            if len(cv_feim) == 0:
                cv_feim = feim.copy()
            else:
                cv_feim = cv_feim.merge(feim, on='feature', how='inner')

        cv_score = np.mean(list_score)
        self.logger.info(f'''
#========================================================================
# Train End.''')
        [self.logger.info(f'''
# Validation No: {i} | {self.metric}: {score}''') for i, score in enumerate(list_score)]
        self.logger.info(f'''
# Params   : {params}
# CV score : {cv_score}
#======================================================================== ''')

        ' fold数で平均をとる '
        prediction = prediction / fold

        ' OOF for Stackng '
        if oof_flg:
            if kaggle == 'ga':
                pred_stack = test.reset_index()[['unique_id', key]]
            else:
                pred_stack = test.reset_index()[key].to_frame()
            pred_stack[target] = prediction
            result_stack = pd.concat([val_stack, pred_stack], axis=0)
            self.logger.info(
                f'result_stack shape: {result_stack.shape} | cnt_id: {len(result_stack[key].drop_duplicates())}')
        else:
            result_stack = []

        importance = []
        for fold_no in range(fold):
            if len(importance) == 0:
                importance = cv_feim[f'{fold_no}_importance'].values.copy()
            else:
                importance += cv_feim[f'{fold_no}_importance'].values

        cv_feim['avg_importance'] = importance / fold
        cv_feim.sort_values(by=f'avg_importance',
                            ascending=False, inplace=True)
        cv_feim['rank'] = np.arange(len(cv_feim))+1

        self.cv_feim = cv_feim
        self.prediction = prediction
        self.cv_score = cv_score
        self.result_stack = result_stack

        return self
