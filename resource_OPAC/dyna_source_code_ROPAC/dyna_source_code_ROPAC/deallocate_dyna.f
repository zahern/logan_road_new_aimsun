      subroutine  deallocate_dyna

      use muc_mod
	use vector_mod
      use intooi_mod
	use LinkList_mod
   	integer error

c	print *, 'Alex7021'
	deallocate(movement,stat=error)
      if(error.ne.0) then
	  print *,"deallocate movement error"
	  stop
	endif

      deallocate(pathindex,stat=error)
      if(error.ne.0) then
	  print *,"deallocate pathindex error"
	  stop
	endif

c	print *, 'Alex7022'	
c	call pathtime_2DRemove()

      deallocate (RemainDwell,stat=error)
      deallocate (DestVisit,stat=error)
	deallocate (bay,stat=error)

c	print *, 'Alex7023'
**************** Start of addition ************************************
	deallocate (right_capacity,stat=error)
	deallocate(bayR,stat=error)
!**************** End of addition ************************************

c 	print *, 'Alex7024'
	deallocate (openalty,stat=error)
	deallocate (link_entry_time,stat=error)
	deallocate (entry_service,stat=error)
	deallocate (entryrate,stat=error)
	deallocate (inentry,stat=error)
	deallocate (link_entry_queue,stat=error)
	deallocate (gcratio,stat=error)
	deallocate (opp_lane,stat=error)
	deallocate (opp_linkP,stat=error)
	deallocate (opp_linkS,stat=error)
	deallocate (volume,stat=error)
	deallocate (vehicle_queue,stat=error)

!****************************************
c	print *, 'Alex7025'
	deallocate (vehicle_queue_PCE,stat=error)
!****************************************


c 	print *, 'Alex7026'
	deallocate (decision, stat=error)
	deallocate (switch,stat=error)
	deallocate (outflow,stat=error)
	deallocate (outleft,stat=error)
	deallocate (left_capacity,stat=error)
	deallocate (node,stat=error)
	deallocate (green,stat=error)
	deallocate (MaxFlowRate, stat=error)
	deallocate (MaxFlowRateOrig, stat=error)
      deallocate (SatFlowRate, stat=error)
	deallocate (link_detector,stat=error)
	deallocate (LoadWeight, stat=error)
	deallocate (LoadWeightID, stat=error)
	deallocate (delaystep,stat=error)
	deallocate (delayleft,stat=error)
	deallocate (aveoutflow,stat=error)
	deallocate (aveoutleft,stat=error)
	deallocate (SignalPreventBack,stat=error)

c 	print *, 'Alex7027'
!	deallocate (SignalPreventFor,stat=error)

	deallocate (iflag,stat=error)
	deallocate (nout,stat=error)
	deallocate (npar,stat=error)
	deallocate (nparold,stat=error)
	deallocate (turnveh,stat=error)
	deallocate (turnvehso,stat=error)
	deallocate (c,stat=error)
	deallocate (v,stat=error)
	deallocate (ctmp,stat=error)
	deallocate (vtmp,stat=error)
	deallocate (ivms,stat=error)
c 	print *, 'Alex7028'
	deallocate(ramp_par,stat=error)
	deallocate(ramp_start,stat=error)
	deallocate(ramp_end,stat=error)
	deallocate(detector,stat=error)
	deallocate(detector_length,stat=error)
	deallocate(detector_ramp,stat=error)
	deallocate(det_link,stat=error)
	deallocate(occup,stat=error)
c 	print *, 'Alex7029'
	deallocate(inci,stat=error)
	deallocate(incistartflag,stat=error)
	deallocate(incil,stat=error)
	deallocate(incilist,stat=error)
	deallocate(itp,stat=error)
c 	print *, 'Alex70291'
	if(allocated(ImpactType))then
      deallocate(ImpactType,stat=error)
	endif
c  	print *, 'Alex70292'
    	deallocate (capacity,stat=error)
	deallocate (captot,stat=error)
	deallocate (nlanes,stat=error)
	deallocate (ttstop,stat=error)
	deallocate (xl,stat=error)
c	print *, 'Alex7030'

	if(allocated(original_xl))then
	deallocate(original_xl,stat=error)
	endif
	if(allocated(LGenerationFlag))then
	deallocate(LGenerationFlag,stat=error)
	endif
	if(allocated(cmax))then
	deallocate(cmax,stat=error)
	endif
	if(allocated(p))then
	deallocate(p,stat=error)
	endif
	if(allocated(vlg))then
	deallocate(vlg,stat=error)
	endif
	if(allocated(vlg_vhcID))then	
	deallocate (vlg_vhcID,stat=error)
	endif

c	print *, 'Alex7030a'

	deallocate (gen,stat=error)
	deallocate (ttilnow,stat=error)
	deallocate (ribf,stat=error)
	deallocate (notin,stat=error)
	deallocate (tleft,stat=error)
	deallocate (tqwait,stat=error)
	deallocate (nmov,stat=error)
	deallocate (compliance,stat=error)
	deallocate (mtnum,stat=error)
	deallocate (atime,stat=error)
	deallocate (partotal,stat=error)
	deallocate (distans,stat=error)
	deallocate (qflag,stat=error)
	deallocate (ntryq,stat=error)
	deallocate (statmpt,stat=error)
c	print *, 'Alex7030b'

!	deallocate (intooi,stat=error)

c      deallocate (TranLink_Array,stat=error)

c  	if(ALLOCATED(TranLink_Array))then
c      do it=1,noofarcs

c   	if(TranLink_Array(it)%PSize>0)then

c	if(associated(TranLink_Array(it)%P))then
c	deallocate(TranLink_Array(it)%P,stat=error)
c	  if(error.ne.0)then
c	    write(911,*)"deallocate TranLink_Array(it)%P vector error"
c	    print *,"deallocate TranLink_Array(it)%P vector error"
c	    pause
c	  endif
c      endif

c	endif

c      enddo
c	deallocate(TranLink_Array,stat=error)
c	endif

	deallocate (intoo,stat=error)
	deallocate (info,stat=error)
	deallocate (nexlink,stat=error)

!	deallocate (BackToForLink,stat=error)


!	deallocate (link_iden,stat=error)

c	print *, 'Alex7031'
!	deallocate (NoofGenLinksPerZone,stat=error)


!	deallocate (LinkNoInZone,stat=error)

	deallocate (NoofConsPerZone,stat=error)
      deallocate (ConNoInZone,stat=error)
	deallocate (zdem,stat=error)
	

	deallocate (zdemT,stat=error)
	deallocate (izone,stat=error)
	deallocate (zfdem,stat=error)


	deallocate (zdemH,stat=error)
	deallocate (zfdemT,stat=error)
	deallocate (ztdemGenH,stat=error)
	deallocate (zfdemH,stat=error)
	deallocate (expgenzH,stat=error)

	deallocate (ztdemGen,stat=error)
	deallocate (ztdemGenT,stat=error)
	deallocate (ztdemAtt,stat=error)
	deallocate (iConZone,stat=error)
	deallocate (iGenZone,stat=error)
	deallocate (TotalLinkLenPerZone,stat=error)
	deallocate (expgenz,stat=error)
	deallocate (expgenzT,stat=error)
	deallocate (expgen,stat=error)
	deallocate (expgenT,stat=error)

c	print *, 'Alex7032'
	deallocate (expgenH,stat=error)

	deallocate (tmp30,stat=error)
	deallocate (tmp31,stat=error)
	deallocate (tmp32,stat=error)
	deallocate (tmp33,stat=error)
	deallocate (tmp34,stat=error)
	deallocate (tmp35,stat=error)
	deallocate (tmp36,stat=error)
	deallocate (tmp37,stat=error)
	deallocate (tmp38,stat=error)
	deallocate (tmp39,stat=error)
	deallocate (tmp40,stat=error)
	deallocate (tocross,stat=error)
	deallocate (linfree,stat=error)
      deallocate (nsign,stat=error)
	deallocate (kgpoint,stat=error)
      deallocate (begint,stat=error)
      deallocate (begintT,stat=error)
 
      deallocate (begintH,stat=error)
	deallocate (strtsig,stat=error)
	deallocate (vmstype,stat=error)
	deallocate (vmstypetwopath,stat=error)
	deallocate (vms,stat=error)
	deallocate (vms_start,stat=error)
	deallocate (vms_end,stat=error)
	deallocate (isel,stat=error)
      deallocate (decisionnum,stat=error)
	deallocate (switchnum,stat=error)
	deallocate (HOVFlag,stat=error)
	deallocate (HOTFlag,stat=error)

c      print *, 'Alex7033'

!      deallocate (GeoPreventFor,stat=error)

      deallocate(GeoPreventBack,stat=error)	 
c      print *, 'Alex70331'	  
      deallocate(WorkZone,stat=error)
c      print *, 'Alex70332'	  
      deallocate(wzstartflag,stat=error)
c      print *, 'Alex70333'	  
      deallocate(total_count,stat=error)
c      print *, 'Alex70334'	  
      deallocate(stopcap4w,stat=error)
c      print *, 'Alex70335'	  
      deallocate(stopcap2w,stat=error)
c      print *, 'Alex70336'	  
      deallocate(stopcap2wIND,stat=error)
c      print *, 'Alex70337'	  
      deallocate(YieldCapIND,stat=error)
c      print *, 'Alex70338'	  
      deallocate(YieldCap,stat=error)
c      print *, 'Alex70339'	  
      deallocate(MGreenS,stat=error)
c      print *, 'Alex703310'	  
      deallocate(FlowModelNum,stat=error)
c      print *, 'Alex703311'	  
      deallocate(FlowModelType,stat=error)
c      print *, 'Alex703312'	  
      deallocate(Vfadjust,stat=error)
c      print *, 'Alex703313'	  
      deallocate(SpeedLimit,stat=error)
	  
c      print *, 'Alex7034'
      if(allocated(DynPCE))then
      deallocate (DynPCE,stat=error)
      endif
	if(allocated(GRDInd))then
	deallocate (GRDInd,stat=error)
	endif
	if(allocated(OriginLinkIndex))then
	deallocate (OriginLinkIndex,stat=error)
	endif
	if(allocated(LENInd))then
	deallocate (LENInd,stat=error)
	endif
	if(allocated(GradeBPnt))then
      deallocate (GradeBPnt,stat=error)
	endif
	if(allocated(LengthBPnt))then
      deallocate (LengthBPnt,stat=error)
	endif
	if(allocated(TruckBPnt))then
	deallocate (TruckBPnt,stat=error)
	endif
	if(allocated(PCE))then
      deallocate (PCE,stat=error)
	endif 
	if(allocated(Truckpct))then           
      deallocate (Truckpct,stat=error)
	endif
	if(allocated(stopcap2wIND))then
      deallocate (stopcap2wIND,stat=error)
	endif 
	if(allocated(YieldCapIND))then     	
      deallocate (YieldCapIND,stat=error)
	endif 
	if(allocated(LGrade))then     	
      deallocate (LGrade,stat=error)
	endif 
	if(allocated(nTruck))then     	
      deallocate (nTruck,stat=error)
	endif 
	if(allocated(AccuVol))then     	
      deallocate (AccuVol,stat=error)
	endif 
	if(allocated(LinkVolume))then     	
      deallocate (LinkVolume,stat=error)
	endif

c	print *, 'Alex7035'
      if(allocated(ConnectorToOriginFlag))then
      deallocate(ConnectorToOriginFlag,stat=error)
      endif
c	print *, 'Alex7036'	
      if(allocated(SignData))then
      deallocate(SignData,stat=error)
      endif
c	print *, 'Alex7037'	
      if(allocated(SignApprh))then
      deallocate(SignApprh,stat=error)
      endif
c	print *, 'Alex7038'
	     deallocate(EntQueVehList)
c	print *, 'Alex7039'	
	     deallocate(LinkVehList)
c	print *, 'Alex7040'	
	     deallocate(TripChainList)

c  	deallocate(p_mtxj_insert%next_veh)
c	print *, 'Alex7041'
C      deallocate(p_mtxj_insert)
c	print *, 'Alex7042'	  
C      deallocate(p_mtxj_remove)
c	print *, 'Alex7043'	  
C      deallocate(p_mtqj_insert)
c	print *, 'Alex7044'	  
C      deallocate(p_mtqj_InsFront)
c	print *, 'Alex7045'	  
C      deallocate(p_TripChain_remove)
c	print *, 'Alex7046'	  
C      deallocate(P_TripChain_insert)

c	if(associated(p_mtxj_value)) 
c	+deallocate(p_mtxj_value)
c	if(associated(p_mtxj_value)) deallocate(p_mtxj_value)
c	deallocate(p_mtqj_remove)
c	deallocate(p_mtqj_value)

c	if(allocated(VhcAtt_Array))then
c   	if(VhcAtt_Array(it)%PSize>0)then
c	do it=1,noofarcs
c     	if(associated(VhcAtt_Array(it)%P))then
c	  DEALLOCATE(VhcAtt_Array(it)%P,stat=error)
c	  if(error.ne.0)then
c	    write(911,*)"deallocate VhcAtt_1DArray vector error"
c	    pause
c	  endif
c   	endif
c	enddo
c	deallocate(VhcAtt_Array)
c	endif
c	endif
c	print *, 'Alex7036'
	
      end subroutine
      