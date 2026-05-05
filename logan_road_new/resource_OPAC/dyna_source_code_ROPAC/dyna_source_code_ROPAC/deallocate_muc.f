      subroutine deallocate_muc

	use muc_mod
	use LinkList_mod
	use INTOOI_MOD
	use VECTOR_MOD
 	integer error
	error=0

c	deallocate(ndest_ah,stat=error)
c	if(error.ne.0) then
c	  print *,"deallocate ndest_ah error"
c	  stop
c      endif

c	deallocate(idests_ah,stat=error)
c	if(error.ne.0) then
c	  print *,"deallocate idests_ah error"
c	  stop
c      endif
      
c	deallocate(jdest_ah,stat=error)
c	if(error.ne.0) then
c	  print *,"deallocate jdest_ah error"
c	  stop
c      endif
	
c	deallocate(wait_ah,stat=error)
c	if(error.ne.0) then
c	  print *,"deallocate wait_ah error"
c	  stop
c      endif
      if(allocated(TravelTime))then
	deallocate(TravelTime,stat=error)
	if(error.ne.0) then
	  print *,"deallocate TravelTime error"
	  stop
      endif
      endif

      if(allocated(TravelPenalty))then
	deallocate(TravelPenalty,stat=error)
	if(error.ne.0) then
	  print *,"deallocate TravelPenalty error"
	  stop
      endif
	endif

	deallocate(TravelLET,stat=error)
	if(error.ne.0) then
	  print *,"deallocate TravelLET error"
	  stop
      endif

	deallocate(moveturnMG,stat=error)
	if(error.ne.0) then
	  print *,"deallocate moveturnMG error"
	  stop
      endif

	deallocate(openaltyMG,stat=error)
	if(error.ne.0) then
	  print *,"deallocate openaltyMG error"
	  stop
      endif

	deallocate(DiffMG,stat=error)
	if(error.ne.0) then
	  print *,"deallocate DiffMG error"
	  stop
      endif

	deallocate(penaltyMG,stat=error)
	if(error.ne.0) then
	  print *,"deallocate penaltyMG error"
	  stop
      endif

	if(allocated(ttmarginal))then
	deallocate(ttmarginal,stat=error)
	if(error.ne.0) then
	  print *,"deallocate ttmarginal error"
	  stop
      endif
	endif

c	deallocate(penaltyMG2,stat=error)
c	if(error.ne.0) then
c	  print *,"deallocate penaltyMG2 error"
c	  stop
c      endif

	deallocate(PenaltyEntry,stat=error)
	if(error.ne.0) then
	  print *,"deallocate PenaltyEntry error"
	  stop
      endif

	deallocate(PenaltyEntryMG,stat=error)
	if(error.ne.0) then
	  print *,"deallocate PenaltyEntryMG error"
	  stop
      endif

c ------- UE	 ------------------------------------------
      if(iue_ok.eq.1) then

	deallocate(uepath_lov,stat=error)
	if(error.ne.0) then
	  print *,"deallocate uepath_lov error"
	  stop
      endif

	deallocate(uepolicy_lov,stat=error)
	if(error.ne.0) then
	  print *,"deallocate uepolicy_lov error"
	  stop
      endif

	deallocate(uenxz_lov,stat=error)
	if(error.ne.0) then
	  print *,"deallocate uenxz_lov error"
	  stop
      endif

	deallocate(NumUePath_lov,stat=error)
	if(error.ne.0) then
	  print *,"deallocate NumUePath_lov error"
	  stop
      endif

	deallocate(ueaccuprob_lov,stat=error)
	if(error.ne.0) then
	  print *,"deallocate ueaccuprob_lov error"
	  stop
      endif

      endif
c  ---------end of UE ------------------------

c -----SO

      if(iso_ok.eq.1) then

	deallocate(sopath_lov,stat=error)
	if(error.ne.0) then
	  print *,"deallocate sopath_lov error"
	  stop
      endif

	deallocate(sopolicy_lov,stat=error)
	if(error.ne.0) then
	  print *,"deallocate sopolicy_lov error"
	  stop
      endif

	deallocate(sonxz_lov,stat=error)
	if(error.ne.0) then
	  print *,"deallocate sonxz_lov error"
	  stop
      endif

	deallocate(NumsoPath_lov,stat=error)
	if(error.ne.0) then
	  print *,"deallocate NumsoPath_lov error"
	  stop
      endif

c	deallocate(Path_SOLinfo,stat=error)
c	if(error.ne.0) then
c	  print *,"deallocate Path_SOLinfo error"
c	  stop
c      endif

c	deallocate(Path_SOLtt,stat=error)
c	if(error.ne.0) then
c	  print *,"deallocate Path_SOLtt error"
c	  stop
c      endif

	deallocate(soaccuprob_lov,stat=error)
	if(error.ne.0) then
	  print *,"deallocate soaccuprob_lov error"
	  stop
      endif

      endif
c ------------end of SO -------------------------------------------

c -----grand path set ---------------------------------------------
      if(iso_ok.eq.1.or.iue_ok.eq.1) then

c	deallocate(mucpath_lov,stat=error)
c	if(error.ne.0) then
c	  print *,"deallocate mucpath_lov error"
c	  stop
c      endif

	deallocate(MucPathAtt_lov,stat=error)
	if(error.ne.0) then
	  print *,"deallocate MucPathAtt_lov error"
	  stop
      endif

	deallocate(NumMucPath_lov,stat=error)
	if(error.ne.0) then
	  print *,"deallocate NumMucPath_lov error"
	  stop
      endif

	endif
c ---------end of Grand Path Set ------------------------------------


c --  If HOV/HOT vehicles exist then allocate memory for 
c --  relevant arrays
c ---------------------------------------- 
	if(total_hov.gt.0.001.and.iue_ok.eq.1) then
c     ----UE-------------
	if(allocated(uepath_hov))then
	deallocate(uepath_hov,stat=error)
	if(error.ne.0) then
	  print *,"deallocate uepath_hov error"
	  stop
      endif
	endif
	if(allocated(uepolicy_hov))then	
	deallocate(uepolicy_hov,stat=error)
	if(error.ne.0) then
	  print *,"deallocate uepolicy_hov error"
	  stop
      endif
	endif
	if(allocated(ueaccuprob_hov))then
	deallocate(ueaccuprob_hov,stat=error)
	if(error.ne.0) then
	  print *,"deallocate ueaccuprob_hov error"
	  stop
      endif
	endif
	if(allocated(uenxz_hov))then
	deallocate(uenxz_hov,stat=error)
	if(error.ne.0) then
	  print *,"deallocate uenxz_hov error"
	  stop
      endif
	endif

	if(allocated(NumUePath_hov))then
	deallocate(NumUePath_hov,stat=error)
	if(error.ne.0) then
	  print *,"deallocate NumUePath_hovv error"
	  stop
      endif
	endif

	endif
c     ----SO-------------
      if(total_hov.gt.0.001.and.iso_ok.eq.1) then
	if(allocated(sopath_hov))then
	deallocate(sopath_hov,stat=error)
	if(error.ne.0) then
	  print *,"deallocate sopath_hov error"
	  stop
      endif
	endif
	if(allocated(sopolicy_hov))then
	deallocate(sopolicy_hov,stat=error)
	if(error.ne.0) then
	  print *,"deallocate sopolicy_hov error"
	  stop
      endif
	endif
	if(allocated(sonxz_hov))then
	deallocate(sonxz_hov,stat=error)
	if(error.ne.0) then
	  print *,"deallocate sonxz_hov error"
	  stop
      endif
	endif
	if(allocated(NumsoPath_hov))then
	deallocate(NumsoPath_hov,stat=error)
	if(error.ne.0) then
	  print *,"deallocate NumsoPath_hov error"
	  stop
      endif
	endif
c	if(allocated(Nsoaccuprob_hov))then
c	deallocate(soaccuprob_hov,stat=error)
c	if(error.ne.0) then
c	  print *,"deallocate soaccuprob_hov error"
c	  stop
c      endif
c	endif

	endif
c     ----Grand Path Set-------------
      if((iso_ok.eq.1.or.iue_ok.eq.1).and.total_hov.gt.0.001) then

c	deallocate(Mucpath_hov,stat=error)
c	if(error.ne.0) then
c	  print *,"deallocate Mucpath_hov error"
c	  stop
c     endif
	if(allocated(MucPathAtt_hov))then
	deallocate(MucPathAtt_hov,stat=error)
	if(error.ne.0) then
	  print *,"deallocate MucPathAtt_hov error"
	  stop
      endif
	endif
	if(allocated(NumMucPath_hov))then
	deallocate(NumMucPath_hov,stat=error)
	if(error.ne.0) then
	  print *,"deallocate NumMucPath_hov error"
	  stop
      endif
	endif

	endif

c ------end of HOV/HOT -----------------------------------------------
c -- deallocate_dyna after last iteration..

c -- deallocate_build_mucpath_lov/hov


c	deallocate(traverse%next_node,stat=error)

c	deallocate(traverse,stat=error)
c	nullify(traverse)
C	IF(ALLOCATED(traverse)) THEN
C	DEALLOCATE(traverse)
C	ENDIF
C	deallocate(traverse%next_node,stat=error)

c -- deallocate_calavg

	deallocate(astmpt,stat=error)
	deallocate(apen,stat=error)
	deallocate(alet,stat=error)
      deallocate(diff,stat=error)
      deallocate(apenal,stat=error)
      deallocate(lint,stat=error)
	deallocate(lfr,stat=error)

      do ix=1,muc_path_total_lov ! only copy up to the OldSize not MucPathAtt_lov
	 do iy=1,noof_master_destinations_original
	   do iz=1,nzones
c --
	if(associated(MUCPath_Lov_Array(iz,iy,ix)%P))then
	  DEALLOCATE(MUCPath_Lov_Array(iz,iy,ix)%P,stat=error)
	  if(error.ne.0)then
	    write(911,*)"deallocate MUCPath_Lov_Array%P vector error"
!	    print *,"deallocate MUCPath_Lov_Array%P vector error"
	    pause
	  endif
      endif
c --
	   enddo
	 enddo
	enddo
      ! Delete the old array
      deallocate(MUCPath_Lov_Array)

c	Deallocate some memory not form MUC

c	print *,'Alex11'

c      deallocate(p_mtxj_insert)
c     deallocate(p_mtxj_remove)
c	deallocate(p_mtqj_insert)
c	deallocate(p_mtqj_InsFront)
c	deallocate(p_TripChain_remove)
c      deallocate(P_TripChain_insert)

c	print *,'Alex12'

	return
	end
