import pandas as pd
from warnings import filterwarnings
import requests
from typing import Optional, Union
import json
import base64
from urllib3.exceptions import TimeoutError
from requests.exceptions import ConnectionError, ReadTimeout

from config import logging


filterwarnings('ignore')


def get_denom_info(denom: str, node_lcd_url: str) -> [str, Optional[str]]:
    """
    Get a base demon and a path for ics20 asset
    :param denom: an asset denom in a network
    :param node_lcd_url: a node LCD url
    :return: a base demon and a path
    """
    if denom[:4] == 'ibc/':
        try:
            _res_json = requests.get(f'{node_lcd_url}/ibc/apps/transfer/v1/denom_traces/{denom[4:]}').json()[
                'denom_trace']
            return str(_res_json['base_denom']), _res_json['path']
        except Exception as _e:
            logging.error(f'Not found denom {denom} node lcd url {node_lcd_url}. Error: {_e}')
            return str(denom), 'Not found'
    else:
        return str(denom), None


def get_type_asset(denom: str) -> str:
    """
    Get an asset type by a denom
    :param denom: an asset denom
    :return: an asset type
    """
    if denom[:4] == 'ibc/':
        return 'ics20'
    if denom[:4] == 'pool' or denom[:10] == 'gamm/pool/':
        return 'pool'
    if denom[:5] == 'cw20:':
        return 'cw20'
    if denom[:9] == 'gravity0x':
        return 'erc20'
    if denom[:8] == 'factory/':
        return 'factory'
    return 'sdk.coin'


def get_assets_supply(node_lcd_url: str,
                      limit: int = 10_000) -> pd.DataFrame:
    """
    Get a dataframe with asset denom and supply
    :param node_lcd_url: node LCD url
    :param limit: max number of query result items
    :return: a dataframe with denom and supply columns
    """
    _assets_supply_json = requests.get(
        url=f'{node_lcd_url}/cosmos/bank/v1beta1/supply?pagination.limit={limit}',
        timeout=5
    ).json()['supply']
    return pd.DataFrame(_assets_supply_json).rename(columns={'amount': 'supply'})


def get_assets_metadata(node_lcd_url: str,
                        limit: int = 10_000) -> pd.DataFrame:
    """
    Get a dataframe with asset metadata
    :param node_lcd_url: node LCD url
    :param limit: max number of query result items
    :return: a dataframe with asset metadata
    """
    _assets_metadata_json = requests.get(
        url=f'{node_lcd_url}/cosmos/bank/v1beta1/denoms_metadata?pagination.limit={limit}'
    ).json()['metadatas']
    return pd.DataFrame(_assets_metadata_json).rename(columns={'base': 'denom'})


def get_channel_id_counterparty_dict(node_lcd_url: str,
                                     limit: int = 10_000) -> dict:
    """
    Get a dictionary from channel id to counterparty channel id
    :param node_lcd_url: node LCD url
    :param limit: max number of query result items
    :return: a dictionary from channel id to counterparty channel id
    """
    _channels_json = requests.get(
        url=f'{node_lcd_url}/ibc/core/channel/v1/channels?pagination.limit={limit}'
    ).json()['channels']
    return {_channel['channel_id']: _channel['counterparty']['channel_id'] for _channel in _channels_json}


def get_chain_id_counterparty_dict(channels: Union[list[str], set[str]],
                                   node_lcd_url: str,
                                   port_id: str = 'transfer') -> dict[str, Optional[str]]:
    """
    Get a dictionary from channel id to counterparty chain id
    :param channels: list of channels
    :param node_lcd_url: node LCD url
    :param port_id: port id
    :return: dictionary from channel id to counterparty chain id
    """
    def _get_counterparty_chain_id(channel: str, port_id: str, node_lcd_url: str) -> Optional[str]:
        try:
            return requests.get(
                url=f'{node_lcd_url}/ibc/core/channel/v1/channels/{channel}/ports/{port_id}/client_state'
                ).json()['identified_client_state']['client_state']['chain_id']
        except KeyError:
            logging.error(f'Key error in get_chain_id_counterparty_dict: '
                          f'channel {channel}, node_lcd_url {node_lcd_url}, port_id {port_id}')
            return None
    return {_channel: _get_counterparty_chain_id(channel=_channel, port_id=port_id, node_lcd_url=node_lcd_url)
            for _channel in channels}


def get_cw20_token_info(contract_address: str,
                        node_lcd_url: str,
                        query: Optional[dict] = None) -> dict:
    """
    Get cw20 token info for given contract
    :param contract_address: a contract address
    :param node_lcd_url: node LCD url
    :param query: a contract query for getting info
    :return: a token info
    """
    if query is None:
        query = {"token_info": {}}

    _query_msg = base64.b64encode(json.dumps(query).encode("utf-8")).decode("utf-8")
    _query = f'{node_lcd_url}/cosmwasm/wasm/v1/contract/{contract_address}/smart/{_query_msg}'
    _res = requests.get(_query).json()

    if 'data' in _res.keys():
        return _res['data']
    if 'code' in _res.keys():
        logging.error(f'contract address {contract_address} node lcd url {node_lcd_url}. Not Implemented')
        return _res
    logging.error(f'contract address {contract_address} node lcd url {node_lcd_url}. Error {_res}')
    return {}


def get_assets(chain_id: str,
               node_lcd_url: str,
               port_id: str = 'transfer',
               limit: int = 10_000) -> pd.DataFrame:
    """
    Get dataframe with assets data for a given network and a given network lcd
    :param chain_id: chain id
    :param node_lcd_url: node LCD url
    :param port_id: connection port id
    :param limit: maximum amount of assets
    :return: dataframe with asset data
    """
    _assets_supply_df = get_assets_supply(node_lcd_url=node_lcd_url, limit=limit)
    _asset_metadata_df = get_assets_metadata(node_lcd_url=node_lcd_url)

    if not _asset_metadata_df.empty:
        _assets_df = _assets_supply_df.merge(_asset_metadata_df,
                                             on='denom',
                                             how='left')
    else:
        _assets_df = _assets_supply_df

    _assets_df.loc[:, ['denom_base', 'path']] = \
        _assets_df.apply(
            lambda row: pd.Series(
                data=get_denom_info(
                    denom=row['denom'],
                    node_lcd_url=node_lcd_url)),
            axis=1).to_numpy()

    _assets_df['channels'] = \
        _assets_df.path.map(
            lambda path: path.replace('/transfer/', 'transfer/').split('transfer/')[1:] if path is not None else None)
    _assets_df['one_channel'] = \
        _assets_df.channels.map(
            lambda _channels: len(_channels) == 1 if _channels is not None else None)

    _channel_set = set([item[0] for item in _assets_df.channels.to_list() if item is not None and len(item) > 0])
    _channel_chain_id_dict = get_chain_id_counterparty_dict(channels=_channel_set,
                                                            node_lcd_url=node_lcd_url,
                                                            port_id=port_id)
    _channel_id_counterparty_dict = get_channel_id_counterparty_dict(node_lcd_url=node_lcd_url)
    _assets_df['chain_id_counterparty'] = \
        _assets_df.channels.map(
            lambda _channels: _channel_chain_id_dict[_channels[0]] if _channels is not None and len(
                _channels) > 0 else None)
    _assets_df['channel_id_counterparty'] = \
        _assets_df.channels.map(
            lambda _channels: _channel_id_counterparty_dict[_channels[0]] if _channels is not None and len(
                _channels) > 0 else None)
    _assets_df['type_asset'] = _assets_df.denom.map(get_type_asset)
    _assets_df['type_asset_base'] = _assets_df.denom_base.map(get_type_asset)
    # TODO  change to a `authority_metadata` request result
    _assets_df['admin'] = _assets_df.apply(
        lambda x: x['denom'].split('/')[1] if x.type_asset == 'factory' else None,
        axis=1)
    _assets_df['chain_id'] = chain_id
    return _assets_df


def extract_assets(chain_id: str, node_lcd_url_list: list[str]) -> bool:
    """
    Get dataframe with assets data for a given network by lcd list
    :param chain_id: network chain id
    :param node_lcd_url_list: list of node lcd urls
    :return: dataframe with asset data
    """
    _asset_df = None
    for _node_lcd_url in node_lcd_url_list[::-1]:
        try:
            logging.info(f'extract lcd for chain id: {chain_id}  node lcd url: {_node_lcd_url}')
            _asset_df = get_assets(chain_id=chain_id, node_lcd_url=_node_lcd_url)
            break
        except (ConnectionError, ReadTimeout, TimeoutError, json.JSONDecodeError) as e:
            logging.error(f'no connection for {chain_id} to lcd {_node_lcd_url}. Error: {e}')
        except Exception as e:
            logging.error(f'no connection for {chain_id} to lcd {_node_lcd_url}. Error: {e}')

    if _asset_df is None:
        logging.info(f'data has not been loaded for {chain_id}, lcd apis not work')
        return False
    _asset_df.to_csv(f'data_csv/assets_{chain_id}.csv')
    logging.info(msg=f'extracted {len(_asset_df):>,} assets for chain_id: `{chain_id}`  node lcd url: {_node_lcd_url}')
    return True
