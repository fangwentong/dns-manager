#!/usr/bin/env python
# coding=utf-8

import json
from aliyunsdkcore import client
from typing import List
from aliyunsdkalidns.request.v20150109.DescribeDomainRecordsRequest import DescribeDomainRecordsRequest
from aliyunsdkalidns.request.v20150109.UpdateDomainRecordRequest import UpdateDomainRecordRequest
from aliyunsdkalidns.request.v20150109.AddDomainRecordRequest import AddDomainRecordRequest
from aliyunsdkalidns.request.v20150109.DescribeDomainRecordInfoRequest import DescribeDomainRecordInfoRequest
from aliyunsdkalidns.request.v20150109.DeleteDomainRecordRequest import DeleteDomainRecordRequest
from dnsmanager.model import DnsRecord


class AliyunDnsOps:
    def __init__(self, access_key_id, access_key_secret, region_id: str = 'cn-hangzhou'):
        self.clt = client.AcsClient(access_key_id, access_key_secret, region_id=region_id)

    def get_domain_records(self, domain, rr, record_type) -> List[DnsRecord]:
        page_no = 1
        result = []
        while True:
            res = self._get_domain_records_by_page(domain, rr, record_type, page_no)
            result += res.get('DomainRecords').get('Record')
            if self.no_more(res):
                break
            page_no = page_no + 1
        return [self._convert_to_dns_record(record) for record in result]

    @staticmethod
    def _convert_to_dns_record(dict_record) -> DnsRecord:
        record = DnsRecord()
        record.id = dict_record['RecordId']
        record.name = dict_record['RR']
        record.type = dict_record['Type']
        record.value = dict_record['Value']
        record.ttl = dict_record['TTL']
        return record

    def _get_domain_records_by_page(self, domain, rr, record_type, page_no):
        desc_domain_req = DescribeDomainRecordsRequest()
        desc_domain_req.set_DomainName(domain)
        desc_domain_req.set_accept_format('JSON')
        desc_domain_req.set_PageNumber(page_no)
        if rr is not None:
            desc_domain_req.set_RRKeyWord(rr)
        if record_type is not None:
            desc_domain_req.set_TypeKeyWord(record_type)
        desc_domain_res = self.clt.do_action_with_exception(desc_domain_req)
        return json.loads(desc_domain_res)

    @staticmethod
    def no_more(desc_domain_res):
        total_count = desc_domain_res.get('TotalCount')
        page_number = desc_domain_res.get('PageNumber')
        page_size = desc_domain_res.get('PageSize')
        current_page_size = len(desc_domain_res.get('DomainRecords').get('Record'))
        return total_count <= (page_number - 1) * page_size + current_page_size

    def desc_domain_record(self, record_id):
        desc_record_req = DescribeDomainRecordInfoRequest()
        desc_record_req.set_RecordId(record_id)
        desc_record_req.set_accept_format('JSON')
        return json.loads(self.clt.do_action_with_exception(desc_record_req))

    # https://help.aliyun.com/document_detail/29774.html
    def update_domain_record(self, domain: str, record: DnsRecord):
        request = UpdateDomainRecordRequest()
        request.set_RecordId(record.id)
        request.set_RR(record.name)
        request.set_Type(record.type)
        request.set_Value(record.value)
        request.set_accept_format('JSON')
        return json.loads(self.clt.do_action_with_exception(request))

    def add_domain_record(self, domain, record: DnsRecord):
        request = AddDomainRecordRequest()
        if record.ttl is not None:
            request.set_TTL(record.ttl)
        request.set_Type(record.type)
        request.set_RR(record.name)
        request.set_Value(record.value)
        request.set_DomainName(domain)
        request.set_accept_format('JSON')
        return json.loads(self.clt.do_action_with_exception(request))

    def delete_domain_record(self, domain, record: DnsRecord):
        request = DeleteDomainRecordRequest()
        request.set_DomainName(domain)
        request.set_RecordId(record.id)
        request.set_accept_format('JSON')
        return json.loads(self.clt.do_action_with_exception(request))


def build_aliyun_dns_client_from_config(config: dict) -> AliyunDnsOps:
    key_id = config.get('id')
    key_secret = config.get('secret')
    return AliyunDnsOps(key_id, key_secret)
