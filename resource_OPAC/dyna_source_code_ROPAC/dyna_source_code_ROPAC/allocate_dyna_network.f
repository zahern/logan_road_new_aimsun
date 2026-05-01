      SUBROUTINE allocate_dyna_network_arc

	use muc_mod
	use LinkList_mod

	integer error

! --  only allocate once because they are used in muc

      if(iteration.eq.0) then

!	allocate (connectivity(noofnodes,noof_master_destinations),
!     +          stat=error)
	allocate (connectivity(noofarcs,noof_master_destinations),
     +          stat=error)
	if(error.ne.0) then
      write(911,*)'allocate connectivity error-insufficient memory'
	  stop
	endif
	connectivity(:,:) = 1

	allocate (link_iden(noofarcs), stat=error)
	if(error.ne.0) then
      write(911,*)'allocate link_iden error-insufficient memory'
	  stop
	endif
	link_iden(:)=0

	allocate (BackToForLink(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate BackToForLink error-insufficient memory'
	  stop
	endif
	BackToForLink(:)=0

	endif

      allocate(movement(noofarcs,nu_ph1,nu_mv),stat=error)
      if(error.ne.0) then
      write(911,*)'allocate movement error-insufficient memory'
	  stop
	endif
	movement(:,:,:) = 0

	allocate(bay(noofarcs),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate bay error-insufficient memory'
	  stop
	endif
!	bay(:)=.False.

      bay(:)= 0


**************** Start of addition ************************************
	allocate(bayR(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate bayR error-insufficient memory'
	  stop
	endif
	bayR(:)=0




******************* Start of Addition ****************************
	allocate (right_capacity(noofarcs),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate right_capacity error - 
     +  insufficient memory'
	  stop
	endif
	right_capacity(:)=0
******************* End of Addition ****************************

	allocate (openalty(noofarcs,nu_mv),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate openalty error-insufficient memory'
	  stop
	endif
	openalty(:,:)=0

      allocate (link_entry_time(noofarcs),stat=error)
	if(error.ne.0) then
      print *,'allocate link_entry_time error- memory'
	  stop
	endif
	link_entry_time(:)=0

	allocate (entry_service(noofarcs,nu_de),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate entry_service error - 
     +  insufficient memory'
	  stop
	endif
	entry_service(:,:)=0

	allocate (entryrate(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate entryrate error-insufficient memory'
	  stop
	endif
	entryrate(:)=0

	allocate (inentry(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate inentry error-insufficient memory'
	  stop
	endif
	inentry(:)=1

	allocate (link_entry_queue(noofarcs),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate link_entry_queue error - 
     +  insufficient memory'
	  stop
	endif
	link_entry_queue(:)=0

	allocate (gcratio(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate gcratio error-insufficient memory'
	  stop
	endif
	gcratio(:)=0

	allocate (opp_lane(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allcoate opp_lane error-insufficient memory'
	  stop
	endif
	opp_lane(:)=0

	allocate (opp_linkP(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate opp_linkP error-insufficient memory'
	  stop
	endif
	opp_linkP(:)=0

	allocate (opp_linkS(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate opp_linkS error-insufficient memory'
	  stop
	endif
	opp_linkS(:)=0

	allocate (volume(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate volumen error-insufficient memory'
	  stop
	endif
	volume(:)=0

	allocate (vehicle_queue(noofarcs),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate vehicle_queue error - 
     +  insufficient memory'
	  stop
	endif
	vehicle_queue=0

	!of trucks on queues
	!*****************************************************
	allocate (vehicle_queue_PCE(noofarcs),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate vehicle_queue_PCE error - 
     +  insufficient memory'
	  stop
	endif
	vehicle_queue_PCE(:)=0
	!*****************************************************

	allocate (outflow(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate outflow error-insufficient memory'
	  stop
	endif
	outflow(:)=0

	allocate (outleft(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate outleft error-insufficient memory'
	  stop
	endif
	outleft(:)=0

	allocate (truckpct(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate truckpct error-memory'
	  stop
	endif
	truckpct(:)=0

	allocate (left_capacity(noofarcs),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate left_capacity error - 
     +  insufficient memory'
	  stop
	endif
	left_capacity(:)=0

	allocate (total_count(noofarcs),stat=error)
	if(error.ne.0) then
       write(911,*)'allocate total_count error-insufficient memory'
	  stop
	endif
	total_count(:)=0

	allocate (green(noofarcs,nu_mv),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate green error-insufficient memory'
	  stop
	endif
	green(:,:)=0

	allocate (stopcap4w(NLevel,NMove),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate stopcap4w error-insufficient memory'
	  stop
	endif
      stopcap4w(:,:)=0

      allocate (stopcap2w(Level2N,Move2N),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate stopcap2w error-insufficient memory'
	  stop
	endif
      stopcap2w(:,:)=0

      allocate (stopcap2wIND(Level2N),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate stopcap2wIND error-insufficient memory'
	  stop
	endif
      stopcap2wIND(:)=0


      allocate (YieldCap(Level2N,Move2N),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate stopcap2w error-insufficient memory'
	  stop
	endif
      stopcap2w(:,:)=0

      allocate (YieldCapIND(Level2N),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate stopcap2wIND error-insufficient memory'
	  stop
	endif
      stopcap2wIND(:)=0


	allocate (MaxFlowRate(noofarcs), stat=error)
	if(error.ne.0) then
      write(911,*)'allocate MaxFlowRate error-insufficient memory'
	  stop
	endif
	MaxFlowRate(:)=0

	allocate (MaxFlowRateOrig(noofarcs), stat=error)
	if(error.ne.0) then
      write(911,*)'allocate MaxFlowRate error-insufficient memory'
	  stop
	endif
	MaxFlowRateOrig(:)=0

	allocate (SatFlowRate(noofarcs), stat=error)
	if(error.ne.0) then
      write(911,*)'allocate SatFlowRate error-insufficient memory'
	  stop
	endif
	SatFlowRate(:)=0

	allocate (LGrade(noofarcs), stat=error)
	if(error.ne.0) then
	  write(911,*)'allocate LGrade error-insufficient memory'
	  stop
	endif
	LGrade(:)=0

	allocate (link_detector(noofarcs),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate link_detector error - 
     +  insufficient memory'
	  stop
	endif
	link_detector(:)=0


!	allocate (link_iden(noofarcs), stat=error)
!	if(error.ne.0) then
!	  write(911,*) 'allocate link_iden error - insufficient memory'
!	  stop
!	endif
!	link_iden(:)=0

	allocate (LoadWeight(noofarcs), stat=error)
	if(error.ne.0) then
      write(911,*) 'allocate LoadWeight error-insufficient memory'
	  stop
	endif
	LoadWeight(:)=0

	allocate (LoadWeightID(nzones), stat=error)
	if(error.ne.0) then
      write(911,*)'allocate LoadWeightID error-insufficient memory'
	  stop
	endif
	LoadWeightID(:)=.False.

	allocate (delaystep(noofarcs,nu_de),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate delaystep error-insufficient memory'
	  stop
	endif
	delaystep(:,:)=0

	allocate (delayleft(noofarcs,nu_de),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate delayleft error-insufficient memory'
	  stop
	endif
	delayleft(:,:)=0

	allocate (aveoutflow(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate aveoutflow error-insufficient memory'
	  stop
	endif
	aveoutflow(:)=0

	allocate (aveoutleft(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate aveoutleft error-insufficient memory'
	  stop
	endif
	aveoutleft(:)=0

	allocate (AccuVol(noofarcs),stat=error)
	if(error.ne.0) then
	  write(911,*)'allocate AccuVol error-insufficient memory'
	  stop
	endif
	AccuVol(:)=0

	allocate (LinkVolume(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate LinkVolume error-insufficient memory'
	  stop
	endif
	LinkVolume(:)=0

	allocate (SignalPreventBack(noofarcs,nu_mv),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate prevent error-insufficient memory'
	  stop
	endif
	SignalPreventBack(:,:)=0


	if(iteration.eq.0) then
	allocate (SignalPreventFor(noofarcs,nu_mv),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate prevent1 error-insufficient memory'
	  stop
	endif
	SignalPreventFor(:,:)=0

	allocate (GeoPreventFor(noofarcs,nu_mv),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate GeoPreventFor error-insufficient memory'
	  stop
	endif
	GeoPreventFor(:,:) = 1

	endif

	allocate (GeoPreventBack(noofarcs,nu_mv),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate GeoPreventBack error-insufficient memory'
	  stop
	endif
	GeoPreventBack(:,:) = 1


	allocate (iflag(noofarcs),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate iflat error - insufficient memory'
	  stop
	endif
	iflag(:)=0

	allocate (nout(noofarcs),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate nout error - insufficient memory'
	  stop
	endif
	nout(:)=0
	
	allocate (npar(noofarcs),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate npar error - insufficient memory'
	  stop
	endif
	npar(:)=0

	allocate (nTruck(noofarcs),stat=error)
	if(error.ne.0) then
	  write(911,*)'allocate nTruck error-insufficient memory'
	  stop
	endif
	nTruck(:)=0

	allocate (nparold(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate nparold error-insufficient memory'
	  stop
	endif
	nparold(:)=0

	allocate (turnveh(noofarcs,nu_mv),stat=error) 
	if(error.ne.0) then
      write(911,*)'allocate turnveh error-insufficient memory'
	  stop
	endif
	turnveh(:,:)=0

	allocate (turnvehso(noofarcs,nu_mv),stat=error)
	if(error.ne.0) then 
      write(911,*)'allocate turnvehso error-insufficient memory'
	  stop
	endif
	turnvehso(:,:)=0

	allocate (c(noofarcs),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate c error-insufficient memory'
	  stop
	endif
	c(:)=0

	allocate (v(noofarcs),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate v error-insufficient memory'
	  stop
	endif
	v(:)=0

	allocate (ctmp(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate ctmp error-insufficient memory'
	  stop
	endif
	ctmp(:)=0

	allocate (vtmp(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate vtmp error-insufficient memory'
	  stop
	endif
	vtmp(:)=0

	allocate (capacity(noofarcs,nu_mv),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate capacity error-insufficient memory'
	  stop
	endif
	capacity(:,:)=0

	allocate (captot(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate captot error-insufficient memory'
	  stop
	endif
	captot(:)=0

	allocate (nlanes(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate nlanes error-insufficient memory'
	  stop
	endif
	nlanes(:)=0
	  
	allocate (xl(noofarcs),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate xl error - insufficient memory'
	  stop
	endif
	xl(:)=0


	allocate (original_xl(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate original_xl error-insufficient memory'
	  stop
	endif
	original_xl(:)=0


	allocate (LGenerationFlag(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate LGenerationFlag error-insufficient memory'
	  stop
	endif
	LGenerationFlag(:)=0




	allocate (cmax(noofarcs),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate cmax error-insufficient memory'
	  stop
	endif
	cmax(:)=0

	allocate (MGreenS(NoOfFlowModel+1),stat=error) ! allocate FlowModelNum+1 for assigning default model for connectors
	if(error.ne.0) then
      write(911,*)'allocate MGreenS error-insufficient memory'
	  stop
	endif
	MGreenS(:)%KCut=0
	MGreenS(:)%Vf2=0
	MGreenS(:)%V02=0
	MGreenS(:)%kjam2=0
	MGreenS(:)%alpha2=0

      allocate (FlowModelNum(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate FlowModelNum error-insufficient memory'
	  stop
	endif
	FlowModelNum(:)=0

      allocate (FlowModelType(NoOfFlowModel+1),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate FlowModelType error-insufficient memory'
	  stop
	endif
	FlowModelType(:)=0

	allocate (Vfadjust(noofarcs),stat=error)
	if(error.ne.0) then
	  write(911,*)'allocate Vfadjust error-insufficient memory'
	  stop
	endif
	Vfadjust(:)=0

	allocate (SpeedLimit(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate SpeedLimit error-insufficient memory'
	  stop
	endif
	SpeedLimit(:)=0

	allocate (vlg(noofarcs),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate vlg error- insufficient memory'
	  stop
	endif
	vlg(:)=0




! we use 1000 for now, please modify the maximum
	allocate (vlg_vhcID(noofarcs,1000),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate vlg_vhcID error-insufficient memory'
	  stop
	endif
	vlg_vhcID(:,:)=0


	allocate (gen(noofarcs),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate gen error-insufficient memory'
	  stop
	endif
	gen(:)=0

	allocate (nmov(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate nmov error-insufficient memory'
	  stop
	endif
	nmov(:)=0

      allocate (partotal(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate partotal error-insufficient memory'
	  stop
	endif
	partotal(:)=0

	allocate (ntryq(noofarcs),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate ntryq error- insufficient memory'
	  stop
	endif
	ntryq(:)=0

	allocate (statmpt(noofarcs),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate statmp error-insufficient memory'
	  stop
	endif
      statmpt(:)=0

	allocate (intoo(noofarcs),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate intoo error-insufficient memory'
	  stop
	endif
	intoo(:)%NVehIn=0
	intoo(:)%NVehOut=0

	allocate (iGenZone(noofarcs,10),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate iGenZone error-insufficient memory'
	  stop
	endif
	iGenZone(:,:)=0

	allocate (expgen(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate expgen error-insufficient memory'
	  stop
	endif
	expgen(:)=0

	allocate (expgenT(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate expgenT error-insufficient memory'
	  stop
	endif
	expgenT(:)=0



	allocate (expgenH(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate expgenH error-insufficient memory'
	  stop
	endif
	expgenH(:)=0


	allocate (tmp30(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate tmp30 error-insufficient memory'
	  stop
	endif
	tmp30(:)=0

	allocate (tmp31(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate imtp31 error-insufficient memory'
	  stop
	endif
	tmp31(:)=0

	allocate (tmp32(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate tmp32 error-insufficient memory'
	  stop
	endif
	tmp32(:)=0

	allocate (tmp33(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate tmp33 error-insufficient memory'
	  stop
	endif
	tmp33(:)=0

	allocate (tmp34(noofarcs),stat=error)
	if(error.ne.0) then 
      write(911,*)'allocate tmp34 error-insufficient memory'
	  stop
	endif
	tmp34(:)=0

	allocate (tmp35(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate tmp35 error-insufficient memory'
	  stop
	endif
	tmp35(:)=0

	allocate (tmp36(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allcoate tmp36 error-insufficient memory'
	  stop
	endif
	tmp36(:)=0

	allocate (tmp37(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate tmp 37 error-insufficient memory'
	  stop
	endif
	tmp37(:)=0

	allocate (tmp38(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate tmp38 error-insufficient memory'
	  stop
	endif
	tmp38(:)=0

	allocate (tmp39(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate tmp39 error-insufficient memory'
	  stop
	endif
	tmp39(:)=0

	allocate (tmp40(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate tmp40 error-insufficient memory'
	  stop
	endif
	tmp40(:)=0


! --  only allocate once because they are used in MUC
 
      if(iteration.eq.0) then

      allocate (UNodeOfBackLink(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate UNodeOfBackLink error-insufficient memory'
	  stop
	endif
	UNodeOfBackLink(:)=0
    	
      allocate (TTimeOfBackLink(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate TTimeOfBackLink error-insufficient memory'
	  stop
	endif
	TTimeOfBackLink(:)=0

      allocate (ForToBackLink(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate ForToBackLink error-insufficient memory'
	  stop
	endif
	ForToBackLink(:)=0

      allocate (s(noofarcs),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate s error - insufficient memory'
	  stop
	endif
	s(:)=0
	
      allocate (idnod(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate idnod error-insufficient memory'
	  stop
	endif
	idnod(:)=0
      
	allocate (penalty(noofarcs,nu_mv),stat=error)
	if(error.ne.0) then
	  write(911,*)'allocate penalty error-insufficient memory'
	  stop
	endif
	penalty(:,:)=0

	allocate(movein(noofarcs,nu_mv+1),stat=error)
	if(error.ne.0) then
	  write(911,*)'allocate movein error-insufficient memory'
	  stop
	endif
	movein(:,:) = 0
      
	allocate(move(noofarcs,nu_mv+1),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate move error-insufficient memory'
	  stop
	endif
	move(:,:) = 0


	allocate(UturnFlag(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate UturnFlag error-insufficient memory'
	  stop
	endif
	UturnFlag(:) = 0
	
	
      allocate (iunod(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate iunod error-insufficient memory'
	  stop
	endif
	iunod(:)=0
      
	allocate(inlink(noofarcs,nu_mv+1),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate noofarcs error-insufficient memory'
	  stop
	endif
	inlink(:,:) = 0

	allocate(llink(noofarcs,nu_mv+1),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate llink error-insufficient memory'
	  stop
	endif
	llink(:,:) = 0

	allocate(topocont(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate topocont error-insufficient memory'
	  stop
	endif
	topocont(:) = 0

      endif

	allocate(linfree(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate linfree error-insufficient memory'
	  stop
	endif
	linfree(:) = 0

      allocate(kgpoint(noofnodes+1),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate kgpoint error-insufficient memory'
	  stop
	endif
	kgpoint(:) = 0

	allocate(LinkVehList(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate LinkVehList error-insufficient memory'
	  stop
	endif

      do i = 1, noofarcs
	 LinkVehList(i)%veh = 0
       nullify(LinkVehList(i)%next_veh)
	enddo

	allocate(EntQueVehList(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate EntQueVehList error-insufficient memory'
	  stop
	endif

      do i = 1, noofarcs
	 EntQueVehList(i)%veh = 0
	 nullify(EntQueVehList(i)%next_veh)
	enddo

	allocate(TripChainList(noofarcs),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate TripChainList error-insufficient memory'
	  stop
	endif

      do i = 1, noofarcs
	 TripChainList(i)%veh = 0
	 nullify(TripChainList(i)%next_veh)
	enddo

      allocate(p_mtxj_insert)
      allocate(p_mtxj_remove)
	allocate(p_mtxj_value,stat=error)
	allocate(p_mtqj_insert)
	allocate(p_mtqj_InsFront)
	allocate(p_mtqj_remove)
	allocate(p_mtqj_value)
	allocate(p_TripChain_remove)
      allocate(P_TripChain_insert)


      allocate(DynPCE(noofarcs),stat=error)
	if(error.ne.0) then 
      write(911,*)'allocate DynPCE error-insufficient memory'
	  stop
	endif
      DynPCE(:)=0.0

	allocate (GRDInd(noofarcs),stat=error)
	if(error.ne.0) then 
      write(911,*)'allocate PCE error-insufficient memory'
	  stop
	endif
      GRDInd(:)=0

	allocate (OriginLinkIndex(noofarcs),stat=error)
	if(error.ne.0) then 
      write(911,*)'allocate OriginLinkIndex error-insufficient memory'
	  stop
	endif
      OriginLinkIndex(:)=0

	allocate (LENInd(noofarcs),stat=error)
	if(error.ne.0) then 
	  write(911,*) 'allocate PCE error - insufficient memory'
	  stop
	endif
      LenInd(:)=0
	
	END SUBROUTINE

      SUBROUTINE ALLOCATE_DYNA_NETWORK_MAXLINKVEH
      use muc_mod
      use intooi_mod

	integer error

	MaxLinkVeh = maxden*Longest_link

!	allocate (intooi(noofarcs,MaxLinkVeh,3),stat=error)
!	if(error.ne.0) then
!	  write(911,*) 'allocate intooi error - insufficient memory'
!	  stop
!	endif
!	intooi(:,:,:)=0
    
      call TranLink_2DSetup(noofarcs)

 	do icount=1,noofarcs
        call TranLink_Setup(icount,10)
      enddo
	       
	allocate(isel(MaxLinkVeh),stat=error)
	if(error.ne.0) then
	  write(911,*)'allocate isel error-insufficient memory'
	  stop
	endif
	isel(:) = 0

	END SUBROUTINE

       SUBROUTINE allocate_dyna_network_node
	use muc_mod
	use LinkList_mod

	integer error

	allocate (node(noofnodes,6),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate node error-insufficient memory'
	  stop
	endif
	node(:,:)=0

	allocate (izone(noofnodes),stat=error)
	if(error.ne.0) then
	  write(911,*)'allocate izone error-insufficient memory'
	  stop
	endif
	izone(:)=0

	allocate (iConZone(noofnodes,4),stat=error) ! only connection to 2 centriods are allowed for now
	if(error.ne.0) then
       write(911,*)'allocate iConZone error-insufficient memory'
	  stop
	endif
	iConZone(:,:)=0

! --  only allocate once because they are used in muc

      if(iteration.eq.0) then

!	allocate (connectivity(noofnodes,noof_master_destinations),
!     +          stat=error)
!	if(error.ne.0) then
!	  write(911,*) 'allocate connectivity error - insufficient memory'
!	  stop
!	endif
!	connectivity(:,:) = 1

c	allocate (CheckCentroid(noof_master_destinations),
c     +          stat=error)
c	if(error.ne.0) then
c	  write(911,*) 'allocate CheckCentroid error - insufficient memory'
c	  stop
c	endif
c      CheckCentroid(:) = .False.

	allocate(BackPointr(noofnodes+1),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate BackPointr error-insufficient memory'
	  stop
	endif
	BackPointr(:) = 0

      allocate(nodenum(noofnodes),stat=error)
 	if(error.ne.0) then
      write(911,*)'allocate nodenum error-insufficient memory'
	  stop
	endif
	nodenum(:)=0

c  -- Currntly the max allowed input node number is 9999
      allocate(idnum(999999),stat=error)
 	if(error.ne.0) then
      write(911,*)'allocate idnum error-insufficient memory'
	  stop
	endif
	idnum(:)=0

      endif

	allocate(nsign(noofnodes*nu_mv,14),stat=error)
	if(error.ne.0) then
      write(911,*)'allcoate nsign error-insufficient memory'
	  stop
	endif
	nsign(:,:) = 0

	END SUBROUTINE
