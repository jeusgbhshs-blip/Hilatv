/** Six chapter 7 shortcuts. The sentence is a starting point the user can edit. */

export type IndustryShortcut = {
  id: string;
  label: string;
  sentence: string;
};

export const INDUSTRIES: IndustryShortcut[] = [
  {
    id: "manufacturing",
    label: "制造业",
    sentence: "给柱塞泵做一条15秒产品宣传片，面向采购，风格稳重",
  },
  {
    id: "foreign_trade",
    label: "外贸出海",
    sentence: "给外贸出海的柱塞泵做一条15秒产品宣传片，面向海外采购商，突出交期",
  },
  {
    id: "ecommerce",
    label: "电商零售",
    sentence: "给这款商品做一条15秒电商带货短视频，用作主图",
  },
  {
    id: "local_life",
    label: "本地生活",
    sentence: "给餐厅做一条15秒探店视频，面向到店客人",
  },
  {
    id: "education",
    label: "教育培训",
    sentence: "给入门课做一条15秒课程宣传片，面向想报名的学员",
  },
  {
    id: "public_sector",
    label: "政企公共",
    sentence: "给高新区做一条15秒招商宣传片，面向企业",
  },
];
